from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from astock.domain.market import Timeframe


class Unit(StrEnum):
    PRICE = "price"
    PERCENT = "percent"
    RATIO = "ratio"
    SHARES = "shares"
    AMOUNT = "amount"
    DAYS = "days"
    BOOLEAN = "boolean"
    CATEGORY = "category"
    SCORE = "score"


class Operator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    NOT_BETWEEN = "not_between"
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"
    AT_LEAST = "at_least"
    CONTINUOUS = "continuous"


class ConstantOperand(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["constant"] = "constant"
    value: bool | float | str | list[float]
    unit: Unit


class MetricOperand(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["metric"] = "metric"
    metric: str
    timeframe: Timeframe
    multiplier: float = 1.0


Operand = Annotated[ConstantOperand | MetricOperand, Field(discriminator="kind")]


class ConditionNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["condition"] = "condition"
    metric: str
    timeframe: Timeframe
    operator: Operator
    right: Operand
    lookback: int | None = Field(default=None, ge=1, le=1000)
    occurrences: int | None = Field(default=None, ge=1, le=1000)


class GroupLogic(StrEnum):
    AND = "and"
    OR = "or"
    NOT = "not"


class GroupNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["group"] = "group"
    logic: GroupLogic
    children: list[ConditionNode | GroupNode]

    @model_validator(mode="after")
    def validate_children(self) -> GroupNode:
        if self.logic == GroupLogic.NOT and len(self.children) != 1:
            raise ValueError("not group requires exactly one child")
        if self.logic != GroupLogic.NOT and not self.children:
            raise ValueError("and/or group requires at least one child")
        return self


Node = Annotated[ConditionNode | GroupNode, Field(discriminator="kind")]
GroupNode.model_rebuild()
