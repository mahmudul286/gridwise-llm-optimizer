import json
import time

from app.llm_parser import parse_operator_notes


FILE_NAME = (
    "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)

DELAY_BETWEEN_CASES_SECONDS = 8


def normalize_adjustment(adjustment):
    if adjustment is None:
        return None

    return {
        key: value
        for key, value in adjustment.items()
        if value is not None
    }


def compare_directives(
    actual,
    expected
):
    if len(actual) != len(expected):
        return False, (
            f"directive count mismatch: "
            f"{len(actual)} != {len(expected)}"
        )

    for index, (
        actual_item,
        expected_item
    ) in enumerate(
        zip(actual, expected)
    ):

        if (
            actual_item.note_index
            != expected_item["note_index"]
        ):
            return False, (
                f"note_index mismatch at {index}"
            )

        if (
            actual_item.applies
            != expected_item["applies"]
        ):
            return False, (
                f"applies mismatch at {index}"
            )

        if (
            actual_item.directive_type
            != expected_item["directive_type"]
        ):
            return False, (
                f"directive_type mismatch at {index}"
            )

        actual_adjustment = (
            normalize_adjustment(
                actual_item.structured_adjustment
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

        if not actual_item.explanation.strip():
            return False, (
                f"empty explanation at {index}"
            )

    return True, ""


def run_debug():

    with open(
        FILE_NAME,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    cases = data.get(
        "cases",
        []
    )

    total = len(cases)
    passed = 0

    print("=" * 60)
    print("GridWise LLM Interpretation Test")
    print("=" * 60)

    for case_index, case in enumerate(
        cases
    ):

        case_id = case["id"]
        payload = case["input"]

        print()
        print("=" * 60)
        print(case_id)
        print("=" * 60)

        try:

            actual = parse_operator_notes(
                payload["operator_notes"],
                payload["battery"][
                    "capacity_kwh"
                ]
            )

            expected = case[
                "expected_output"
            ][
                "directive_interpretation"
            ]

            ok, reason = compare_directives(
                actual,
                expected
            )

            if ok:

                passed += 1

                for item in actual:
                    print(
                        f"note_index={item.note_index} "
                        f"applies={item.applies} "
                        f"type={item.directive_type} "
                        f"adjustment={item.structured_adjustment}"
                    )

                print(
                    f"PASS: {case_id}"
                )

            else:

                print(
                    f"FAIL: {case_id}"
                )
                print(
                    f"Reason: {reason}"
                )

        except Exception as exc:

            print(
                f"FAIL: {case_id}"
            )
            print(
                f"Error: {type(exc).__name__}: {exc}"
            )

        # Avoid hammering provider token limits during
        # local diagnostics.
        if case_index < total - 1:

            time.sleep(
                DELAY_BETWEEN_CASES_SECONDS
            )

    print()
    print("=" * 60)
    print(
        f"RESULT: {passed}/{total} interpretation tests passed"
    )
    print("=" * 60)


if __name__ == "__main__":
    run_debug()