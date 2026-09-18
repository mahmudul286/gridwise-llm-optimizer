import json
import time
import os
import requests


FILE_NAME = (
    "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)

BASE_URL = os.getenv(
    "BASE_URL",
    "http://localhost:8000"
)

OPTIMIZE_URL = (
    f"{BASE_URL}/optimize-energy"
)

TOLERANCE = 0.01
HTTP_TIMEOUT = 60

HTTP_RETRIES = 2
HTTP_RETRY_DELAY = 8


VALID_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def close_enough(
    actual,
    expected
):
    return abs(
        float(actual) - float(expected)
    ) <= TOLERANCE


def normalize_adjustment(
    adjustment
):
    if adjustment is None:
        return None

    return {
        key: value
        for key, value in adjustment.items()
        if value is not None
    }


def compare_directive_semantics(
    actual,
    expected
):

    if len(actual) != len(expected):
        return False, (
            f"Expected {len(expected)} directives, "
            f"got {len(actual)}"
        )

    for index, (
        actual_item,
        expected_item
    ) in enumerate(
        zip(actual, expected)
    ):

        if (
            actual_item["note_index"]
            != expected_item["note_index"]
        ):
            return False, (
                f"note_index mismatch at {index}"
            )

        if (
            actual_item["applies"]
            != expected_item["applies"]
        ):
            return False, (
                f"applies mismatch at {index}"
            )

        if (
            actual_item["directive_type"]
            not in VALID_DIRECTIVE_TYPES
        ):
            return False, (
                f"unsupported directive type at {index}"
            )

        if (
            actual_item["directive_type"]
            != expected_item["directive_type"]
        ):
            return False, (
                f"directive_type mismatch at {index}: "
                f"actual={actual_item['directive_type']}, "
                f"expected={expected_item['directive_type']}"
            )

        actual_adjustment = (
            normalize_adjustment(
                actual_item[
                    "structured_adjustment"
                ]
            )
        )

        expected_adjustment = (
            normalize_adjustment(
                expected_item[
                    "structured_adjustment"
                ]
            )
        )

        if actual_adjustment != expected_adjustment:
            return False, (
                f"structured_adjustment mismatch at {index}: "
                f"actual={actual_adjustment}, "
                f"expected={expected_adjustment}"
            )

        if (
            not isinstance(
                actual_item["explanation"],
                str
            )
            or not actual_item[
                "explanation"
            ].strip()
        ):
            return False, (
                f"empty explanation at {index}"
            )

    return True, ""


def replay_plan(
    payload,
    result,
):
    tolerance = TOLERANCE

    hours = sorted(
        payload["hours"],
        key=lambda x: x["hour"]
    )

    battery = payload["battery"]

    directives = result[
        "directive_interpretation"
    ]

    plan = result[
        "hourly_plan"
    ]

    if len(plan) != 24:
        return False, (
            "hourly_plan must contain exactly 24 entries"
        )

    # ========================================================
    # Build effective constraints
    # ========================================================

    original_solar = [
        hour["solar_kwh"]
        for hour in hours
    ]

    effective_solar = (
        original_solar.copy()
    )

    minimum_reserve = [
        battery[
            "minimum_energy_kwh"
        ]
        for _ in range(24)
    ]

    no_charge = set()
    no_discharge = set()

    max_grid = [
        float("inf")
        for _ in range(24)
    ]

    for directive in directives:

        if not directive["applies"]:
            continue

        adjustment = directive[
            "structured_adjustment"
        ]

        if not adjustment:
            continue

        used_hours = adjustment.get(
            "hours",
            []
        )

        directive_type = (
            directive["directive_type"]
        )

        if directive_type == (
            "solar_reduction"
        ):

            factor = float(
                adjustment["factor"]
            )

            for hour in used_hours:

                candidate = (
                    original_solar[hour]
                    * factor
                )

                effective_solar[hour] = min(
                    effective_solar[hour],
                    candidate
                )

        elif directive_type == (
            "minimum_battery_reserve"
        ):

            reserve = float(
                adjustment[
                    "minimum_energy_kwh"
                ]
            )

            for hour in used_hours:

                minimum_reserve[hour] = max(
                    minimum_reserve[hour],
                    reserve
                )

        elif directive_type == (
            "no_charge_window"
        ):

            no_charge.update(
                used_hours
            )

        elif directive_type == (
            "no_discharge_window"
        ):

            no_discharge.update(
                used_hours
            )

        elif directive_type == (
            "max_grid_window"
        ):

            cap = float(
                adjustment[
                    "max_grid_kwh"
                ]
            )

            for hour in used_hours:

                max_grid[hour] = min(
                    max_grid[hour],
                    cap
                )

    # ========================================================
    # Replay
    # ========================================================

    battery_energy = float(
        battery[
            "initial_energy_kwh"
        ]
    )

    recalculated_grid = 0.0
    recalculated_cost = 0.0

    peak_grid = 0.0

    for expected_hour, entry in enumerate(
        plan
    ):

        # ----------------------------------------------------
        # Sequential hours
        # ----------------------------------------------------

        if entry["hour"] != expected_hour:

            return False, (
                f"Hour sequence mismatch at index "
                f"{expected_hour}"
            )

        source_hour = hours[
            expected_hour
        ]

        # ----------------------------------------------------
        # Action
        # ----------------------------------------------------

        action = entry[
            "battery_action"
        ]

        battery_kwh = float(
            entry["battery_kwh"]
        )

        if action == "charge":

            charge = battery_kwh
            discharge = 0.0

            if charge <= tolerance:
                return False, (
                    f"Invalid charge amount at hour "
                    f"{expected_hour}"
                )

            if charge > (
                battery[
                    "max_charge_kwh_per_hour"
                ]
                + tolerance
            ):
                return False, (
                    f"Charge rate exceeded at hour "
                    f"{expected_hour}"
                )

        elif action == "discharge":

            charge = 0.0
            discharge = battery_kwh

            if discharge <= tolerance:
                return False, (
                    f"Invalid discharge amount at hour "
                    f"{expected_hour}"
                )

            if discharge > (
                battery[
                    "max_discharge_kwh_per_hour"
                ]
                + tolerance
            ):
                return False, (
                    f"Discharge rate exceeded at hour "
                    f"{expected_hour}"
                )

        elif action == "idle":

            charge = 0.0
            discharge = 0.0

            if battery_kwh > tolerance:
                return False, (
                    f"Idle battery_kwh is non-zero at "
                    f"hour {expected_hour}"
                )

        else:

            return False, (
                f"Invalid battery_action "
                f"at hour {expected_hour}"
            )

        # ----------------------------------------------------
        # Solar cap
        # ----------------------------------------------------

        solar_used = float(
            entry["solar_used_kwh"]
        )

        if solar_used > (
            effective_solar[
                expected_hour
            ]
            + tolerance
        ):

            return False, (
                f"Solar cap exceeded at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # No charge
        # ----------------------------------------------------

        if (
            expected_hour in no_charge
            and charge > tolerance
        ):

            return False, (
                f"Charging prohibited at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # No discharge
        # ----------------------------------------------------

        if (
            expected_hour in no_discharge
            and discharge > tolerance
        ):

            return False, (
                f"Discharging prohibited at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Max grid
        # ----------------------------------------------------

        grid = float(
            entry["grid_kwh"]
        )

        if grid > (
            max_grid[
                expected_hour
            ]
            + tolerance
        ):

            return False, (
                f"Grid cap exceeded at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Energy balance
        # ----------------------------------------------------

        demand = float(
            source_hour["demand_kwh"]
        )

        balance = (
            grid
            + solar_used
            + discharge
            - charge
            - demand
        )

        if abs(balance) > tolerance:

            return False, (
                f"Energy balance failed at hour "
                f"{expected_hour}: "
                f"difference={balance}"
            )

        # ----------------------------------------------------
        # Battery state
        # ----------------------------------------------------

        battery_energy = (
            battery_energy
            + charge
            - discharge
        )

        returned_energy = float(
            entry[
                "battery_energy_after_kwh"
            ]
        )

        if abs(
            returned_energy
            - battery_energy
        ) > tolerance:

            return False, (
                f"Battery transition failed at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Battery capacity
        # ----------------------------------------------------

        if (
            returned_energy
            < minimum_reserve[
                expected_hour
            ]
            - tolerance
        ):

            return False, (
                f"Battery reserve violated at hour "
                f"{expected_hour}"
            )

        if (
            returned_energy
            > battery["capacity_kwh"]
            + tolerance
        ):

            return False, (
                f"Battery capacity exceeded at hour "
                f"{expected_hour}"
            )

        # ----------------------------------------------------
        # Totals
        # ----------------------------------------------------

        recalculated_grid += grid

        recalculated_cost += (
            grid
            * float(
                source_hour[
                    "tariff_bdt_per_kwh"
                ]
            )
        )

        peak_grid = max(
            peak_grid,
            grid
        )

    # ========================================================
    # End-of-day neutrality
    # ========================================================

    initial_energy = float(
        battery[
            "initial_energy_kwh"
        ]
    )

    if abs(
        battery_energy
        - initial_energy
    ) > tolerance:

        return False, (
            "End-of-day neutrality violated"
        )

    # ========================================================
    # Returned totals
    # ========================================================

    returned_total_grid = float(
        result["total_grid_kwh"]
    )

    returned_total_cost = float(
        result["total_cost_bdt"]
    )

    returned_peak_grid = float(
        result["peak_grid_kwh"]
    )

    if not close_enough(
        returned_total_grid,
        recalculated_grid
    ):

        return False, (
            "total_grid_kwh does not match "
            "hourly_plan"
        )

    if not close_enough(
        returned_total_cost,
        recalculated_cost
    ):

        return False, (
            "total_cost_bdt does not match "
            "hourly_plan"
        )

    if not close_enough(
        returned_peak_grid,
        peak_grid
    ):

        return False, (
            "peak_grid_kwh does not match "
            "hourly_plan"
        )

    return True, ""


def post_with_retry(
    payload
):

    last_response = None

    for attempt in range(
        HTTP_RETRIES + 1
    ):

        try:

            response = requests.post(
                OPTIMIZE_URL,
                json=payload,
                timeout=HTTP_TIMEOUT
            )

            last_response = response

            if response.status_code == 200:
                return response

            if (
                response.status_code
                in {429, 500, 502, 503, 504}
                and attempt < HTTP_RETRIES
            ):

                time.sleep(
                    HTTP_RETRY_DELAY
                )

                continue

            return response

        except requests.RequestException:

            if attempt >= HTTP_RETRIES:
                raise

            time.sleep(
                HTTP_RETRY_DELAY
            )

    return last_response


def run_tests():

    # ========================================================
    # Load public samples
    # ========================================================

    try:

        with open(
            FILE_NAME,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

    except FileNotFoundError:

        print(
            f"Missing file: {FILE_NAME}"
        )

        return

    cases = data.get(
        "cases",
        []
    )

    # ========================================================
    # Health
    # ========================================================

    try:

        health = requests.get(
            f"{BASE_URL}/health",
            timeout=10
        )

        if health.status_code != 200:
            print(
                "❌ Health check failed"
            )
            return

        health_data = health.json()

        if health_data.get("status") != "ok":
            print(
                "❌ Health response is invalid"
            )
            return

        print(
            "✅ Health check passed"
        )

    except Exception:

        print(
            "❌ Server is not running"
        )
        return

    # ========================================================
    # Cases
    # ========================================================

    passed = 0

    print()
    print("=" * 60)
    print(
        f"Running {len(cases)} public sample cases"
    )
    print("=" * 60)

    for case_index, case in enumerate(
        cases
    ):

        case_id = case["id"]

        print()
        print(
            f"[{case_id}]"
        )

        payload = case["input"]

        try:

            response = post_with_retry(
                payload
            )

        except Exception as exc:

            print(
                f"❌ {case_id}: "
                f"request failed: "
                f"{type(exc).__name__}"
            )

            continue

        if response.status_code != 200:

            print(
                f"❌ {case_id}: "
                f"API returned "
                f"{response.status_code}"
            )

            continue

        try:

            result = response.json()

        except Exception:

            print(
                f"❌ {case_id}: invalid JSON response"
            )

            continue

        # ----------------------------------------------------
        # Directive semantics
        # ----------------------------------------------------

        expected_directives = (
            case[
                "expected_output"
            ][
                "directive_interpretation"
            ]
        )

        directive_ok, directive_reason = (
            compare_directive_semantics(
                result[
                    "directive_interpretation"
                ],
                expected_directives
            )
        )

        if not directive_ok:

            print(
                f"❌ {case_id}: "
                f"directive mismatch: "
                f"{directive_reason}"
            )

            continue

        # ----------------------------------------------------
        # Plan replay
        # ----------------------------------------------------

        replay_ok, replay_reason = (
            replay_plan(
                payload,
                result
            )
        )

        if not replay_ok:

            print(
                f"❌ {case_id}: "
                f"plan validation failed: "
                f"{replay_reason}"
            )

            continue

        # ----------------------------------------------------
        # Expected optimal cost
        # ----------------------------------------------------

        expected_cost = float(
            case[
                "expected_output"
            ][
                "total_cost_bdt"
            ]
        )

        actual_cost = float(
            result[
                "total_cost_bdt"
            ]
        )

        if not close_enough(
            actual_cost,
            expected_cost
        ):

            print(
                f"❌ {case_id}: "
                f"cost mismatch. "
                f"expected={expected_cost}, "
                f"actual={actual_cost}"
            )

            continue

        passed += 1

        print(
            f"✅ {case_id} PASS | "
            f"Cost={actual_cost:.2f} BDT"
        )

        if case_index < len(cases) - 1:

            # Avoid provider rate-limit pressure
            # during local sequential testing.
            time.sleep(
                8
            )

    # ========================================================
    # Summary
    # ========================================================

    print()
    print("=" * 60)
    print(
        f"FINAL RESULT: {passed}/{len(cases)} passed"
    )
    print("=" * 60)


if __name__ == "__main__":
    run_tests()