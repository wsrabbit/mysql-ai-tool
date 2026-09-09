from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Limits(StrictModel):
    default_rows: int = Field(default=200, ge=1, le=1000)
    max_rows: int = Field(default=1000, ge=1, le=1000)
    max_bytes: int = Field(default=1_048_576, ge=4096, le=1_048_576)
    field_bytes: int = Field(default=8192, ge=128, le=8192)
    query_seconds: int = Field(default=10, ge=1, le=30)
    connect_seconds: int = Field(default=5, ge=1, le=10)
    concurrency: int = Field(default=2, ge=1, le=2)
    queue_size: int = Field(default=4, ge=0, le=8)
    queue_seconds: int = Field(default=5, ge=1, le=10)


class ConnectionProfile(StrictModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = Field(min_length=1, max_length=128)
    databases: list[str] = Field(min_length=1, max_length=32)
    environment: str = Field(default="dev", max_length=32)
    tls: Literal["verify", "disabled"] = "verify"
    ssl_ca: str | None = None
    password_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    credential_id: str = Field(min_length=1, max_length=128)

    @field_validator("databases")
    @classmethod
    def databases_valid(cls, values: list[str]) -> list[str]:
        forbidden = {"mysql", "sys", "information_schema", "performance_schema"}
        for value in values:
            if not value or len(value) > 64 or any(c in value for c in "\x00`/\\."):
                raise ValueError("Invalid database identifier")
            if value.lower() in forbidden:
                raise ValueError("System databases cannot be configured as business databases")
        if len(values) != len(set(values)):
            raise ValueError("Duplicate database names")
        return values


class Settings(StrictModel):
    schema_version: Literal[1] = 1
    limits: Limits = Field(default_factory=Limits)
    connections: dict[str, ConnectionProfile] = Field(default_factory=dict)

    @field_validator("connections")
    @classmethod
    def aliases_valid(cls, value: dict) -> dict:
        import re

        if len(value) > 32:
            raise ValueError("At most 32 connection profiles are supported")
        for alias in value:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", alias):
                raise ValueError("Invalid connection alias")
        return value
