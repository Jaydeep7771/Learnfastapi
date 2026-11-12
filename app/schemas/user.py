import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Password = Annotated[str, Field(min_length=10, max_length=128)]


class UserCreate(BaseModel):
    """INPUT schema. Accepts a raw password - which no output schema can ever echo."""

    email: EmailStr
    password: Password
    role: Literal["user", "admin"] = "user"

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if v.lower() == v or v.upper() == v:
            raise ValueError("password must mix upper and lower case")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain a digit")
        return v


class UserRead(BaseModel):
    """OUTPUT schema. hashed_password is not declared, so it cannot leak - even if
    the ORM object carries it. This is the data-leak firewall."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    created_at: dt.datetime
