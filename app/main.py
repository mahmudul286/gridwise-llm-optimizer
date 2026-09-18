import logging
from typing import List

from fastapi import FastAPI, HTTPException

from app.llm_parser import parse_operator_notes
from app.optimizer import solve_energy_schedule
from app.schemas import (
    BatterySpec,
    DirectiveInterpretation,
    HourData,
    HourlyPlanEntry,
    OptimizeRequest,
    OptimizeResponse,
)


logger = logging.getLogger(
    "gridwise"
)

app = FastAPI(
    title="GridWise LLM Optimizer"
)


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health_check():
    return {
        "status": "ok"
    }


# ============================================================
# BUILD EFFECTIVE CONSTRAINTS FOR FINAL VALIDATION
# ============================================================

def build_validation_constraints(
    hours_data: List[HourData],
    battery: BatterySpec,
    directives: List[DirectiveInterpretation],
):
    original_solar = [
        hour.solar_kwh
        for hour in hours_data
    ]

    effective_solar = original_solar.copy()

    minimum_reserves = [
        battery.minimum_energy_kwh
        for _ in range(24)
    ]

    no_charge_hours = set()
    no_discharge_hours = set()

    max_grid_limits = [
        float("inf")
        for _ in range(24)
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

    return (
        effective_solar,
        minimum_reserves,
        no_charge_hours,
        no_discharge_hours,
        max_grid_limits,
    )


# ============================================================
# FINAL INDEPENDENT PLAN VALIDATION
# ============================================================

def validate_final_plan(
    plan: List[HourlyPlanEntry],
    hours_data: List[HourData],
    battery: BatterySpec,
    directives: List[DirectiveInterpretation],
) -> None:

    tolerance = 0.01

    if len(plan) != 24:

        raise ValueError(
            "Final validation failed: plan must contain 24 hours"
        )

    (
        effective_solar,
        minimum_reserves,
        no_charge_hours,
        no_discharge_hours,
        max_grid_limits,
    ) = build_validation_constraints(
        hours_data,
        battery,
        directives,
    )

    battery_energy = (
        battery.initial_energy_kwh
    )

    for expected_hour, entry in enumerate(plan):

        if entry.hour != expected_hour:

            raise ValueError(
                f"Final validation failed: "
                f"expected hour {expected_hour}, "
                f"got {entry.hour}"
            )

        demand = (
            hours_data[
                expected_hour
            ].demand_kwh
        )

        # ----------------------------------------------------
        # Battery action
        # ----------------------------------------------------

        if entry.battery_action == "charge":

            charge = entry.battery_kwh
            discharge = 0.0

            if charge <= tolerance:
                raise ValueError(
                    f"Invalid charge action at hour {expected_hour}"
                )

            if charge > (
                battery.max_charge_kwh_per_hour
                + tolerance
            ):
                raise ValueError(
                    f"Charge rate exceeded at hour {expected_hour}"
                )

        elif entry.battery_action == "discharge":

            charge = 0.0
            discharge = entry.battery_kwh

            if discharge <= tolerance:
                raise ValueError(
                    f"Invalid discharge action at hour {expected_hour}"
                )

            if discharge > (
                battery.max_discharge_kwh_per_hour
                + tolerance
            ):
                raise ValueError(
                    f"Discharge rate exceeded at hour {expected_hour}"
                )

        elif entry.battery_action == "idle":

            charge = 0.0
            discharge = 0.0

            if entry.battery_kwh > tolerance:
                raise ValueError(
                    f"Idle action has non-zero battery_kwh "
                    f"at hour {expected_hour}"
                )

        else:

            raise ValueError(
                f"Unsupported battery action at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Solar
        # ----------------------------------------------------

        if entry.solar_used_kwh > (
            effective_solar[expected_hour]
            + tolerance
        ):

            raise ValueError(
                f"Solar limit exceeded at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # No charge
        # ----------------------------------------------------

        if (
            expected_hour in no_charge_hours
            and charge > tolerance
        ):

            raise ValueError(
                f"Charging prohibited at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # No discharge
        # ----------------------------------------------------

        if (
            expected_hour in no_discharge_hours
            and discharge > tolerance
        ):

            raise ValueError(
                f"Discharging prohibited at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Grid limit
        # ----------------------------------------------------

        if entry.grid_kwh > (
            max_grid_limits[expected_hour]
            + tolerance
        ):

            raise ValueError(
                f"Grid limit exceeded at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Energy balance
        # ----------------------------------------------------

        balance = (
            entry.grid_kwh
            + entry.solar_used_kwh
            + discharge
            - charge
            - demand
        )

        if abs(balance) > tolerance:

            raise ValueError(
                f"Energy balance failed at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Battery transition
        # ----------------------------------------------------

        battery_energy = (
            battery_energy
            + charge
            - discharge
        )

        if abs(
            entry.battery_energy_after_kwh
            - battery_energy
        ) > tolerance:

            raise ValueError(
                f"Battery transition failed at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Battery bounds
        # ----------------------------------------------------

        if (
            entry.battery_energy_after_kwh
            < minimum_reserves[expected_hour]
            - tolerance
        ):

            raise ValueError(
                f"Battery reserve violated at hour "
                f"{expected_hour}"
            )

        if (
            entry.battery_energy_after_kwh
            > battery.capacity_kwh
            + tolerance
        ):

            raise ValueError(
                f"Battery capacity exceeded at hour "
                f"{expected_hour}"
            )

    # ========================================================
    # End-of-day neutrality
    # ========================================================

    if abs(
        battery_energy
        - battery.initial_energy_kwh
    ) > tolerance:

        raise ValueError(
            "End-of-day battery neutrality violated"
        )


# ============================================================
# OPTIMIZATION ENDPOINT
# ============================================================

@app.post(
    "/optimize-energy",
    response_model=OptimizeResponse
)
def optimize_energy(
    req: OptimizeRequest
):

    try:

        sorted_hours = sorted(
            req.hours,
            key=lambda item: item.hour
        )

        # ----------------------------------------------------
        # 1. LLM interpretation
        # ----------------------------------------------------

        directives = parse_operator_notes(
            req.operator_notes,
            req.battery.capacity_kwh
        )

        # ----------------------------------------------------
        # 2. Mathematical optimization
        # ----------------------------------------------------

        plan = solve_energy_schedule(
            sorted_hours,
            req.battery,
            directives
        )

        # ----------------------------------------------------
        # 3. Independent final validation
        # ----------------------------------------------------

        validate_final_plan(
            plan=plan,
            hours_data=sorted_hours,
            battery=req.battery,
            directives=directives,
        )

        # ----------------------------------------------------
        # 4. Recalculate totals from returned plan
        # ----------------------------------------------------

        total_grid = round(
            sum(
                item.grid_kwh
                for item in plan
            ),
            2
        )

        total_cost = round(
            sum(
                item.grid_kwh
                * sorted_hours[
                    item.hour
                ].tariff_bdt_per_kwh
                for item in plan
            ),
            2
        )

        peak_grid = round(
            max(
                item.grid_kwh
                for item in plan
            ),
            2
        )

        # ----------------------------------------------------
        # 5. Response
        # ----------------------------------------------------

        return OptimizeResponse(
            scenario_id=req.scenario_id,
            directive_interpretation=directives,
            hourly_plan=plan,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
            plan_summary=(
                "Operator notes were interpreted by the LLM, "
                "validated deterministically, optimized using "
                "linear programming, and independently checked."
            ),
        )

    except HTTPException:
        raise

    except Exception as exc:

        # Do NOT log stack traces or request payloads.
        logger.error(
            "Optimization pipeline failed: %s",
            type(exc).__name__
        )

        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )