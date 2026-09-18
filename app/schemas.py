from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]

BatteryAction = Literal[
    "charge",
    "discharge",
    "idle",
]


class BatterySpec(BaseModel):
    capacity_kwh: float = Field(ge=0)
    initial_energy_kwh: float = Field(ge=0)
    minimum_energy_kwh: float = Field(ge=0)
    max_charge_kwh_per_hour: float = Field(ge=0)
    max_discharge_kwh_per_hour: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_battery(self):
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError(
                "initial_energy_kwh cannot exceed capacity_kwh"
            )

        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError(
                "minimum_energy_kwh cannot exceed capacity_kwh"
            )

        return self


class HourData(BaseModel):
    hour: int = Field(ge=0, le=23)
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)


class OptimizeRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: List[str] = Field(min_length=1, max_length=3)
    hours: List[HourData] = Field(min_length=24, max_length=24)
    battery: BatterySpec

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "scenario_id cannot be blank"
            )

        return value

    @field_validator("operator_notes")
    @classmethod
    def validate_operator_notes(
        cls,
        value: List[str]
    ) -> List[str]:

        cleaned = []

        for index, note in enumerate(value):
            if not isinstance(note, str):
                raise ValueError(
                    f"operator_notes[{index}] must be a string"
                )

            note = note.strip()

            if not note:
                raise ValueError(
                    f"operator_notes[{index}] cannot be blank"
                )

            cleaned.append(note)

        return cleaned

    @model_validator(mode="after")
    def validate_hours(self):
        hours = [item.hour for item in self.hours]

        if (
            len(hours) != 24
            or len(set(hours)) != 24
            or set(hours) != set(range(24))
        ):
            raise ValueError(
                "hours must contain each integer from 0 through 23 exactly once"
            )

        return self


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(ge=0)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[Dict[str, Any]] = None
    explanation: str = Field(min_length=1)


class HourlyPlanEntry(BaseModel):
    hour: int = Field(ge=0, le=23)
    grid_kwh: float = Field(ge=0)
    solar_used_kwh: float = Field(ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(ge=0)
    battery_energy_after_kwh: float = Field(ge=0)


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float = Field(ge=0)
    total_cost_bdt: float = Field(ge=0)
    peak_grid_kwh: float = Field(ge=0)
    plan_summary: str = Field(min_length=1)