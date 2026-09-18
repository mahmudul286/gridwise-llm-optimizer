import json
import math
import os
import re
import time
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from app.schemas import DirectiveInterpretation


# ============================================================
# CONFIGURATION
# ============================================================

LLM_MODEL = os.getenv(
    "GROQ_MODEL",
    "qwen/qwen3.8-27b"
)

LLM_TIMEOUT = float(
    os.getenv("LLM_TIMEOUT_SECONDS", "15")
)

LLM_MAX_OUTPUT_TOKENS = int(
    os.getenv("LLM_MAX_OUTPUT_TOKENS", "300")
)

LLM_MAX_ATTEMPTS = int(
    os.getenv("LLM_MAX_ATTEMPTS", "3")
)


# ============================================================
# SIMPLE IN-MEMORY CACHE
# ============================================================

_PARSE_CACHE: Dict[
    Tuple[Tuple[str, ...], float],
    List[DirectiveInterpretation]
] = {}

MAX_CACHE_SIZE = 128


# ============================================================
# STRICT JSON SCHEMA
# ============================================================

GRIDWISE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "directives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note_index": {
                        "type": "integer"
                    },

                    "applies": {
                        "type": "boolean"
                    },

                    "directive_type": {
                        "type": "string",
                        "enum": [
                            "solar_reduction",
                            "minimum_battery_reserve",
                            "no_charge_window",
                            "no_discharge_window",
                            "max_grid_window",
                            "no_op"
                        ]
                    },

                    "structured_adjustment": {
                        "anyOf": [
                            {
                                "type": "null"
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "hours": {
                                        "type": "array",
                                        "items": {
                                            "type": "integer"
                                        }
                                    },

                                    "factor": {
                                        "type": [
                                            "number",
                                            "null"
                                        ]
                                    },

                                    "minimum_energy_kwh": {
                                        "type": [
                                            "number",
                                            "null"
                                        ]
                                    },

                                    "max_grid_kwh": {
                                        "type": [
                                            "number",
                                            "null"
                                        ]
                                    }
                                },

                                "required": [
                                    "hours",
                                    "factor",
                                    "minimum_energy_kwh",
                                    "max_grid_kwh"
                                ],

                                "additionalProperties": False
                            }
                        ]
                    },

                    "explanation": {
                        "type": "string"
                    }
                },

                "required": [
                    "note_index",
                    "applies",
                    "directive_type",
                    "structured_adjustment",
                    "explanation"
                ],

                "additionalProperties": False
            }
        }
    },

    "required": [
        "directives"
    ],

    "additionalProperties": False
}


# ============================================================
# JSON CLEANING
# ============================================================

def clean_json_content(
    content: str
) -> str:

    content = content.strip()

    if content.startswith("```"):

        lines = content.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]

        content = "\n".join(lines).strip()

    return content


# ============================================================
# FINITE NUMBER VALIDATION
# ============================================================

def validate_finite_number(
    value: Any,
    field_name: str,
    directive_position: int
) -> float:

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise ValueError(
            f"Directive {directive_position}: "
            f"{field_name} must be numeric"
        )

    value = float(value)

    if not math.isfinite(value):
        raise ValueError(
            f"Directive {directive_position}: "
            f"{field_name} must be finite"
        )

    return value


# ============================================================
# ADJUSTMENT NORMALIZATION
# ============================================================

def normalize_adjustment(
    adjustment: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Strict schema requires all possible adjustment properties.
    Irrelevant nullable properties are removed before
    directive-specific semantic validation.
    """

    return {
        key: value
        for key, value in adjustment.items()
        if value is not None
    }


# ============================================================
# DETERMINISTIC VALIDATION
# ============================================================

def validate_llm_directives(
    items: Any,
    notes: List[str],
    battery_cap: float
) -> List[DirectiveInterpretation]:

    if not isinstance(items, list):
        raise ValueError(
            "'directives' must be an array"
        )

    if len(items) != len(notes):
        raise ValueError(
            f"Expected {len(notes)} directives, "
            f"got {len(items)}"
        )

    expected_indices = list(
        range(len(notes))
    )

    valid_types = {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    }

    required_fields = {
        "note_index",
        "applies",
        "directive_type",
        "structured_adjustment",
        "explanation"
    }

    results: List[
        DirectiveInterpretation
    ] = []

    # ========================================================
    # PER DIRECTIVE
    # ========================================================

    for position, raw_item in enumerate(items):

        if not isinstance(
            raw_item,
            dict
        ):
            raise ValueError(
                f"Directive {position} must be an object"
            )

        missing = (
            required_fields
            - set(raw_item.keys())
        )

        if missing:
            raise ValueError(
                f"Directive {position} missing fields: "
                f"{sorted(missing)}"
            )

        extra = (
            set(raw_item.keys())
            - required_fields
        )

        if extra:
            raise ValueError(
                f"Directive {position} has unsupported fields: "
                f"{sorted(extra)}"
            )

        item = dict(raw_item)

        # ----------------------------------------------------
        # note_index
        # ----------------------------------------------------

        note_index = item["note_index"]

        if type(note_index) is not int:
            raise ValueError(
                f"Directive {position}: "
                "note_index must be integer"
            )

        if note_index != expected_indices[position]:
            raise ValueError(
                f"Directive {position}: "
                "incorrect note_index order"
            )

        # ----------------------------------------------------
        # applies
        # ----------------------------------------------------

        applies = item["applies"]

        if type(applies) is not bool:
            raise ValueError(
                f"Directive {position}: "
                "applies must be boolean"
            )

        # ----------------------------------------------------
        # directive type
        # ----------------------------------------------------

        directive_type = item["directive_type"]

        if directive_type not in valid_types:
            raise ValueError(
                f"Directive {position}: "
                f"unsupported directive type '{directive_type}'"
            )

        # ----------------------------------------------------
        # explanation
        # ----------------------------------------------------

        explanation = item["explanation"]

        if not isinstance(
            explanation,
            str
        ):
            raise ValueError(
                f"Directive {position}: "
                "explanation must be string"
            )

        explanation = explanation.strip()

        if not explanation:
            raise ValueError(
                f"Directive {position}: "
                "explanation cannot be empty"
            )

        item["explanation"] = explanation

        # ====================================================
        # NO-OP
        # ====================================================

        if directive_type == "no_op":

            if applies is not False:
                raise ValueError(
                    f"Directive {position}: "
                    "no_op requires applies=false"
                )

            if item["structured_adjustment"] is not None:
                raise ValueError(
                    f"Directive {position}: "
                    "no_op requires null adjustment"
                )

            results.append(
                DirectiveInterpretation(**item)
            )

            continue

        # ====================================================
        # NON-NO-OP
        # ====================================================

        if applies is not True:
            raise ValueError(
                f"Directive {position}: "
                "non-no_op requires applies=true"
            )

        adjustment = item[
            "structured_adjustment"
        ]

        if not isinstance(
            adjustment,
            dict
        ):
            raise ValueError(
                f"Directive {position}: "
                "structured_adjustment must be object"
            )

        adjustment = normalize_adjustment(
            adjustment
        )

        item["structured_adjustment"] = adjustment

        # ----------------------------------------------------
        # Hours
        # ----------------------------------------------------

        if "hours" not in adjustment:
            raise ValueError(
                f"Directive {position}: "
                "missing hours"
            )

        hours = adjustment["hours"]

        if not isinstance(
            hours,
            list
        ):
            raise ValueError(
                f"Directive {position}: "
                "hours must be a list"
            )

        if not hours:
            raise ValueError(
                f"Directive {position}: "
                "hours cannot be empty"
            )

        if not all(
            type(hour) is int
            and 0 <= hour <= 23
            for hour in hours
        ):
            raise ValueError(
                f"Directive {position}: "
                "hours must contain integers 0-23"
            )

        if len(hours) != len(set(hours)):
            raise ValueError(
                f"Directive {position}: "
                "hours must be unique"
            )

        if hours != sorted(hours):
            raise ValueError(
                f"Directive {position}: "
                "hours must be ascending"
            )

        # ====================================================
        # SOLAR REDUCTION
        # ====================================================

        if directive_type == "solar_reduction":

            required_keys = {
                "hours",
                "factor"
            }

            if set(adjustment.keys()) != required_keys:
                raise ValueError(
                    f"Directive {position}: "
                    "solar_reduction requires "
                    "hours and factor only"
                )

            factor = validate_finite_number(
                adjustment["factor"],
                "factor",
                position
            )

            if not 0.0 <= factor <= 1.0:
                raise ValueError(
                    f"Directive {position}: "
                    "factor must be between 0 and 1"
                )

            adjustment["factor"] = factor

        # ====================================================
        # MINIMUM BATTERY RESERVE
        # ====================================================

        elif directive_type == (
            "minimum_battery_reserve"
        ):

            required_keys = {
                "hours",
                "minimum_energy_kwh"
            }

            if set(adjustment.keys()) != required_keys:
                raise ValueError(
                    f"Directive {position}: "
                    "minimum_battery_reserve requires "
                    "hours and minimum_energy_kwh only"
                )

            reserve = validate_finite_number(
                adjustment["minimum_energy_kwh"],
                "minimum_energy_kwh",
                position
            )

            if not 0.0 <= reserve <= battery_cap:
                raise ValueError(
                    f"Directive {position}: "
                    "minimum_energy_kwh must be "
                    "within battery capacity"
                )

            adjustment[
                "minimum_energy_kwh"
            ] = reserve

        # ====================================================
        # NO CHARGE
        # ====================================================

        elif directive_type == (
            "no_charge_window"
        ):

            if set(adjustment.keys()) != {
                "hours"
            }:
                raise ValueError(
                    f"Directive {position}: "
                    "no_charge_window requires only hours"
                )

        # ====================================================
        # NO DISCHARGE
        # ====================================================

        elif directive_type == (
            "no_discharge_window"
        ):

            if set(adjustment.keys()) != {
                "hours"
            }:
                raise ValueError(
                    f"Directive {position}: "
                    "no_discharge_window requires only hours"
                )

        # ====================================================
        # MAX GRID
        # ====================================================

        elif directive_type == (
            "max_grid_window"
        ):

            required_keys = {
                "hours",
                "max_grid_kwh"
            }

            if set(adjustment.keys()) != required_keys:
                raise ValueError(
                    f"Directive {position}: "
                    "max_grid_window requires "
                    "hours and max_grid_kwh only"
                )

            max_grid = validate_finite_number(
                adjustment["max_grid_kwh"],
                "max_grid_kwh",
                position
            )

            if max_grid < 0:
                raise ValueError(
                    f"Directive {position}: "
                    "max_grid_kwh cannot be negative"
                )

            adjustment["max_grid_kwh"] = max_grid

        # ----------------------------------------------------
        # Final Pydantic validation
        # ----------------------------------------------------

        try:
            results.append(
                DirectiveInterpretation(**item)
            )
        except Exception as exc:
            raise ValueError(
                f"Directive {position}: "
                f"schema validation failed: {exc}"
            ) from exc

    return results


# ============================================================
# PROMPT BUILDER
# ============================================================

def build_prompt(
    notes: List[str],
    battery_cap: float,
    retry_error: str | None = None
) -> str:

    prompt = f"""
You are the GridWise operator-note interpreter.

Interpret operator notes into supported energy directives.
Do NOT optimize the schedule.

Battery capacity: {battery_cap} kWh.

SUPPORTED DIRECTIVES
- solar_reduction
- minimum_battery_reserve
- no_charge_window
- no_discharge_window
- max_grid_window
- no_op

RULES
1. Return exactly one directive per input note.
2. Preserve input note order.
3. note_index must be 0, 1, 2, ... in exact order.
4. Relevant note => applies=true.
5. Irrelevant note => applies=false and directive_type="no_op".
6. no_op => structured_adjustment=null.
7. Every non-no_op directive => applies=true.
8. Explanation is mandatory and must be short.
9. Do not invent unsupported directive types.
10. Do not invent values.

TIME
- Start inclusive, end exclusive.
- "1 PM to 3 PM" => [13,14]
- "noon to 2 PM" => [12,13]
- "2 AM until 5 AM" => [2,3,4]

SOLAR
factor means usable fraction remaining.
- "25% of forecast" => 0.25
- "reduced to 25%" => 0.25
- "80% reduction" => 0.20
- "50% reduction" => 0.50
- "half" => 0.50

RESERVE
Convert percentage reserve into kWh using battery capacity.
Example:
50% of a {battery_cap} kWh battery => {battery_cap * 0.5} kWh.

STRUCTURED ADJUSTMENT

solar_reduction:
{{
  "hours": [...],
  "factor": number,
  "minimum_energy_kwh": null,
  "max_grid_kwh": null
}}

minimum_battery_reserve:
{{
  "hours": [...],
  "factor": null,
  "minimum_energy_kwh": number,
  "max_grid_kwh": null
}}

no_charge_window:
{{
  "hours": [...],
  "factor": null,
  "minimum_energy_kwh": null,
  "max_grid_kwh": null
}}

no_discharge_window:
{{
  "hours": [...],
  "factor": null,
  "minimum_energy_kwh": null,
  "max_grid_kwh": null
}}

max_grid_window:
{{
  "hours": [...],
  "factor": null,
  "minimum_energy_kwh": null,
  "max_grid_kwh": number
}}

For no_op:
"structured_adjustment": null

Return only the required JSON object.
No markdown.
No extra commentary.
""".strip()

    if retry_error:

        prompt += f"""

The previous response failed deterministic validation.

Validation error:
{retry_error}

Return the complete corrected JSON.
""".strip()

    return prompt


# ============================================================
# RETRY WAIT
# ============================================================

def get_retry_wait_seconds(
    error: Exception,
    default_seconds: float = 8.0
) -> float:

    response = getattr(
        error,
        "response",
        None
    )

    if response is not None:

        headers = getattr(
            response,
            "headers",
            None
        )

        if headers:

            retry_after = headers.get(
                "retry-after"
            )

            if retry_after:

                try:
                    return max(
                        1.0,
                        float(retry_after)
                    )
                except (
                    ValueError,
                    TypeError
                ):
                    pass

    message = str(error)

    match = re.search(
        r"try again in\s+"
        r"([0-9]+(?:\.[0-9]+)?)s",
        message,
        re.IGNORECASE
    )

    if match:

        try:
            return max(
                1.0,
                float(match.group(1)) + 0.5
            )
        except (
            ValueError,
            TypeError
        ):
            pass

    return default_seconds


# ============================================================
# MAIN PARSER
# ============================================================

def parse_operator_notes(
    notes: List[str],
    battery_cap: float
) -> List[DirectiveInterpretation]:

    # --------------------------------------------------------
    # Input validation
    # --------------------------------------------------------

    if not isinstance(
        notes,
        list
    ):
        raise ValueError(
            "notes must be a list"
        )

    if not 1 <= len(notes) <= 3:
        raise ValueError(
            "GridWise requires 1 to 3 operator notes"
        )

    if (
        isinstance(battery_cap, bool)
        or not isinstance(
            battery_cap,
            (int, float)
        )
        or battery_cap < 0
        or not math.isfinite(
            float(battery_cap)
        )
    ):
        raise ValueError(
            "battery_cap must be a finite non-negative number"
        )

    clean_notes: List[str] = []

    for index, note in enumerate(notes):

        if not isinstance(
            note,
            str
        ):
            raise ValueError(
                f"Note {index} must be a string"
            )

        note = note.strip()

        if not note:
            raise ValueError(
                f"Note {index} cannot be blank"
            )

        clean_notes.append(note)

    # --------------------------------------------------------
    # Cache
    # --------------------------------------------------------

    cache_key = (
        tuple(clean_notes),
        float(battery_cap)
    )

    if cache_key in _PARSE_CACHE:

        cached = _PARSE_CACHE[
            cache_key
        ]

        return [
            DirectiveInterpretation(
                note_index=item.note_index,
                applies=item.applies,
                directive_type=item.directive_type,
                structured_adjustment=(
                    None
                    if item.structured_adjustment is None
                    else dict(
                        item.structured_adjustment
                    )
                ),
                explanation=item.explanation
            )
            for item in cached
        ]

    # --------------------------------------------------------
    # API key
    # --------------------------------------------------------

    api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured"
        )

    # --------------------------------------------------------
    # Groq client through OpenAI-compatible SDK
    # --------------------------------------------------------

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        max_retries=0
    )

    last_error: str | None = None

    # ========================================================
    # RETRY LOOP
    # ========================================================

    for attempt in range(
        LLM_MAX_ATTEMPTS
    ):

        try:

            prompt = build_prompt(
                notes=clean_notes,
                battery_cap=float(
                    battery_cap
                ),
                retry_error=(
                    last_error
                    if attempt > 0
                    else None
                )
            )

            notes_json = json.dumps(
                clean_notes,
                ensure_ascii=False,
                separators=(",", ":")
            )

            response = client.chat.completions.create(
                model=LLM_MODEL,

                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Return only the required "
                            "GridWise JSON object."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            prompt
                            + "\n\nINPUT NOTES:\n"
                            + notes_json
                        )
                    }
                ],

                temperature=0.0,

                max_tokens=LLM_MAX_OUTPUT_TOKENS,

                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "gridwise_directives",
                        "strict": True,
                        "schema": GRIDWISE_RESPONSE_SCHEMA
                    }
                },

                timeout=LLM_TIMEOUT
            )

            if not response.choices:
                raise ValueError(
                    "LLM returned no choices"
                )

            content = (
                response
                .choices[0]
                .message
                .content
            )

            if not content:
                raise ValueError(
                    "LLM returned empty content"
                )

            content = clean_json_content(
                content
            )

            try:

                data = json.loads(
                    content
                )

            except json.JSONDecodeError as exc:

                raise ValueError(
                    f"Invalid JSON returned by LLM: {exc}"
                ) from exc

            if not isinstance(
                data,
                dict
            ):
                raise ValueError(
                    "LLM response must be a JSON object"
                )

            if "directives" not in data:
                raise ValueError(
                    "LLM response missing 'directives'"
                )

            # ------------------------------------------------
            # Deterministic guardrails
            # ------------------------------------------------

            results = validate_llm_directives(
                items=data["directives"],
                notes=clean_notes,
                battery_cap=float(
                    battery_cap
                )
            )

            # ------------------------------------------------
            # Cache
            # ------------------------------------------------

            if len(_PARSE_CACHE) >= MAX_CACHE_SIZE:

                oldest_key = next(
                    iter(_PARSE_CACHE)
                )

                del _PARSE_CACHE[
                    oldest_key
                ]

            _PARSE_CACHE[
                cache_key
            ] = results

            print(
                "LLM interpretation validated "
                f"on attempt "
                f"{attempt + 1}/{LLM_MAX_ATTEMPTS}"
            )

            return [
                DirectiveInterpretation(
                    note_index=item.note_index,
                    applies=item.applies,
                    directive_type=item.directive_type,
                    structured_adjustment=(
                        None
                        if item.structured_adjustment is None
                        else dict(
                            item.structured_adjustment
                        )
                    ),
                    explanation=item.explanation
                )
                for item in results
            ]

        except Exception as exc:

            last_error = str(exc)

            status_code = getattr(
                exc,
                "status_code",
                None
            )

            print(
                f"LLM attempt "
                f"{attempt + 1}/{LLM_MAX_ATTEMPTS} failed: "
                f"{last_error}"
            )

            if attempt >= (
                LLM_MAX_ATTEMPTS - 1
            ):
                break

            # ------------------------------------------------
            # Rate limit
            # ------------------------------------------------

            if status_code == 429:

                wait_seconds = (
                    get_retry_wait_seconds(
                        exc,
                        default_seconds=8.0
                    )
                )

                print(
                    f"Waiting {wait_seconds:.1f}s "
                    "before retry..."
                )

                time.sleep(
                    wait_seconds
                )

            # ------------------------------------------------
            # Temporary server/provider problem
            # ------------------------------------------------

            elif status_code in {
                500,
                502,
                503,
                504
            }:

                wait_seconds = (
                    2.0 * (attempt + 1)
                )

                print(
                    f"Temporary provider error; "
                    f"waiting {wait_seconds:.1f}s..."
                )

                time.sleep(
                    wait_seconds
                )

            # ------------------------------------------------
            # Validation/schema failure
            # ------------------------------------------------

            else:

                time.sleep(
                    0.5
                )

    raise RuntimeError(
        "LLM interpretation failed after "
        f"{LLM_MAX_ATTEMPTS} attempts: "
        f"{last_error}"
    )