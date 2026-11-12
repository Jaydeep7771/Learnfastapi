import datetime as dt
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

Name = Annotated[str, Field(min_length=2, max_length=120)]
PriceCents = Annotated[int, Field(ge=0, le=100_000_00)]


class ItemCreate(BaseModel):
    name: Name
    description: str | None = Field(default=None, max_length=2000)
    price_cents: PriceCents = 0

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v


class ItemUpdate(BaseModel):
    """PATCH schema: every field optional. `exclude_unset=True` at the call site is
    what distinguishes "field absent" from "field explicitly set to null"."""

    name: Name | None = None
    description: str | None = Field(default=None, max_length=2000)
    price_cents: PriceCents | None = None


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    price_cents: int
    owner_id: int
    created_at: dt.datetime
    updated_at: dt.datetime | None

    @computed_field  # serialization-time derived field, never stored
    @property
    def price_display(self) -> str:
        return f"${self.price_cents / 100:,.2f}"


class Page[T: BaseModel](BaseModel):
    """Generic envelope so every list endpoint paginates the same way."""

    items: list[T]
    total: int
    limit: int
    offset: int
