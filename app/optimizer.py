from typing import List

import numpy as np
from scipy.optimize import linprog

from app.schemas import (
    BatterySpec,
    DirectiveInterpretation,
    HourData,
    HourlyPlanEntry,
)


def solve_energy_schedule(
    hours_data: List[HourData],
    battery: BatterySpec,
    directives: List[DirectiveInterpretation],
) -> List[HourlyPlanEntry]:

    T = 24

    if len(hours_data) != T:
        raise ValueError(
            "Optimizer requires exactly 24 hourly records"
        )

    # ========================================================
    # Build effective constraints
    # ========================================================

    original_solar = [
        hour.solar_kwh
        for hour in hours_data
    ]

    effective_solar = original_solar.copy()

    minimum_reserves = [
        battery.minimum_energy_kwh
        for _ in range(T)
    ]

    no_charge_hours = set()
    no_discharge_hours = set()

    max_grid_limits = [
        float("inf")
        for _ in range(T)
    ]

    for directive in directives:

        if not directive.applies:
            continue

        adjustment = (
            directive.structured_adjustment
        )

        if not adjustment:
            continue

        hours = adjustment.get(
            "hours",
            []
        )

        if directive.directive_type == (
            "solar_reduction"
        ):

            factor = float(
                adjustment["factor"]
            )

            for hour in hours:

                candidate = (
                    original_solar[hour]
                    * factor
                )

                effective_solar[hour] = min(
                    effective_solar[hour],
                    candidate
                )

        elif directive.directive_type == (
            "minimum_battery_reserve"
        ):

            reserve = float(
                adjustment[
                    "minimum_energy_kwh"
                ]
            )

            for hour in hours:

                minimum_reserves[hour] = max(
                    minimum_reserves[hour],
                    reserve
                )

        elif directive.directive_type == (
            "no_charge_window"
        ):

            no_charge_hours.update(
                hours
            )

        elif directive.directive_type == (
            "no_discharge_window"
        ):

            no_discharge_hours.update(
                hours
            )

        elif directive.directive_type == (
            "max_grid_window"
        ):

            max_grid = float(
                adjustment[
                    "max_grid_kwh"
                ]
            )

            for hour in hours:

                max_grid_limits[hour] = min(
                    max_grid_limits[hour],
                    max_grid
                )

    # ========================================================
    # LP variable layout
    # ========================================================
    #
    # For each hour:
    #
    #   0 -> grid import
    #   1 -> solar used
    #   2 -> battery charge
    #   3 -> battery discharge
    #   4 -> battery energy after hour
    #
    # ========================================================

    def idx(
        hour: int,
        variable: int
    ) -> int:

        return hour * 5 + variable

    NUM_VARIABLES = T * 5

    # ========================================================
    # Objective
    # ========================================================

    objective = np.zeros(
        NUM_VARIABLES
    )

    for hour in range(T):

        objective[
            idx(hour, 0)
        ] = hours_data[
            hour
        ].tariff_bdt_per_kwh

    # ========================================================
    # Bounds
    # ========================================================

    bounds = [
        (0, None)
        for _ in range(NUM_VARIABLES)
    ]

    for hour in range(T):

        # Grid
        bounds[
            idx(hour, 0)
        ] = (
            0,
            max_grid_limits[hour]
        )

        # Solar
        bounds[
            idx(hour, 1)
        ] = (
            0,
            effective_solar[hour]
        )

        # Charge
        bounds[
            idx(hour, 2)
        ] = (
            0,
            0
            if hour in no_charge_hours
            else battery.max_charge_kwh_per_hour
        )

        # Discharge
        bounds[
            idx(hour, 3)
        ] = (
            0,
            0
            if hour in no_discharge_hours
            else battery.max_discharge_kwh_per_hour
        )

        # Battery energy
        bounds[
            idx(hour, 4)
        ] = (
            minimum_reserves[hour],
            battery.capacity_kwh
        )

    # ========================================================
    # Equality constraints
    # ========================================================
    #
    # 24 energy-balance equations
    # 24 battery transition equations
    # 1 end-of-day neutrality equation
    #
    # ========================================================

    NUM_EQ = (
        2 * T
        + 1
    )

    A_eq = np.zeros(
        (NUM_EQ, NUM_VARIABLES)
    )

    b_eq = np.zeros(
        NUM_EQ
    )

    row = 0

    # --------------------------------------------------------
    # Energy balance
    #
    # grid + solar + discharge - charge = demand
    # --------------------------------------------------------

    for hour in range(T):

        A_eq[
            row,
            idx(hour, 0)
        ] = 1.0

        A_eq[
            row,
            idx(hour, 1)
        ] = 1.0

        A_eq[
            row,
            idx(hour, 2)
        ] = -1.0

        A_eq[
            row,
            idx(hour, 3)
        ] = 1.0

        b_eq[row] = (
            hours_data[
                hour
            ].demand_kwh
        )

        row += 1

    # --------------------------------------------------------
    # Battery transition
    #
    # E_t = E_(t-1) + charge - discharge
    # --------------------------------------------------------

    for hour in range(T):

        A_eq[
            row,
            idx(hour, 4)
        ] = 1.0

        A_eq[
            row,
            idx(hour, 2)
        ] = -1.0

        A_eq[
            row,
            idx(hour, 3)
        ] = 1.0

        if hour == 0:

            b_eq[row] = (
                battery.initial_energy_kwh
            )

        else:

            A_eq[
                row,
                idx(hour - 1, 4)
            ] = -1.0

            b_eq[row] = 0.0

        row += 1

    # --------------------------------------------------------
    # End-of-day neutrality
    # --------------------------------------------------------

    A_eq[
        row,
        idx(23, 4)
    ] = 1.0

    b_eq[row] = (
        battery.initial_energy_kwh
    )

    # ========================================================
    # Solve
    # ========================================================

    result = linprog(
        c=objective,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )

    if not result.success:

        raise ValueError(
            f"Optimization failed: {result.message}"
        )

    solution = result.x

    # ========================================================
    # Convert solution -> API plan
    # ========================================================

    plan: List[
        HourlyPlanEntry
    ] = []

    for hour in range(T):

        grid_kwh = float(
            round(
                solution[
                    idx(hour, 0)
                ],
                4
            )
        )

        solar_used_kwh = float(
            round(
                solution[
                    idx(hour, 1)
                ],
                4
            )
        )

        charge = float(
            round(
                solution[
                    idx(hour, 2)
                ],
                4
            )
        )

        discharge = float(
            round(
                solution[
                    idx(hour, 3)
                ],
                4
            )
        )

        battery_energy = float(
            round(
                solution[
                    idx(hour, 4)
                ],
                4
            )
        )

        # ----------------------------------------------------
        # Simultaneous charge/discharge should not occur.
        # ----------------------------------------------------

        if charge > 0.01 and discharge > 0.01:

            raise ValueError(
                f"Unexpected simultaneous battery "
                f"charge/discharge at hour {hour}"
            )

        if charge > 0.01:

            action = "charge"
            battery_kwh = charge

        elif discharge > 0.01:

            action = "discharge"
            battery_kwh = discharge

        else:

            action = "idle"
            battery_kwh = 0.0

        plan.append(
            HourlyPlanEntry(
                hour=hour,
                grid_kwh=grid_kwh,
                solar_used_kwh=solar_used_kwh,
                battery_action=action,
                battery_kwh=float(
                    round(
                        battery_kwh,
                        4
                    )
                ),
                battery_energy_after_kwh=battery_energy,
            )
        )

    return plan