from typing import Any
from pydantic import BaseModel, Field

SNAKE_CASE = r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"


class State(BaseModel):
    data: dict[str, Any]


class Constraint(BaseModel):
    id: str = Field(
        pattern=SNAKE_CASE,
        description="Short English snake_case name of the limit, e.g. budget_cap, unique within the problem",
    )
    text: str = Field(description="The limit itself, in the same language as the goal")
    hard: bool = Field(True, description="True if it must never be violated, False for a preference")


class Problem(BaseModel):
    state: State
    goal: str
    constraints: list[Constraint]


def constraints_text(constraints: list[Constraint]) -> str:
    """The constraints as a prompt list, soft ones marked."""
    return "\n".join(f"- {c.text}" + ("" if c.hard else " (preference)") for c in constraints) or "None"


class Action(BaseModel):
    id: str = Field(
        pattern=SNAKE_CASE,
        description=(
            "Short English snake_case verb phrase that names what the action does, "
            "e.g. take_public_transit; never a generic index like action_1"
        ),
    )
    description: str


class ActionSpace(BaseModel):
    actions: list[Action]

