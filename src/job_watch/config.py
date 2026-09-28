"""Load and validate config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["national", "local", "public", "federal"]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_path: str = "~/.local/share/job-watch/jobs.db"
    request_delay_seconds: float = 2.0
    user_agent: str = "job-watch/0.1 (personal job search)"
    max_retries: int = 4
    backoff_base_seconds: float = 2.0
    respect_robots_txt: bool = True
    timeout_seconds: float = 30.0

    @property
    def db_file(self) -> Path:
        return Path(self.db_path).expanduser()


class LevelFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class DisciplineFilter(BaseModel):
    """Civil/transportation gate.

    Passes when something in ``include`` matches (title or department), or
    when nothing in ``exclude`` matches and a ``generic`` word (e.g.
    "engineer") is in the title.
    """

    model_config = ConfigDict(extra="forbid")

    include: list[str] = Field(default_factory=list)
    generic: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    match_fields: list[Literal["title", "department"]] = Field(
        default_factory=lambda: ["title", "department"]
    )


class LocationFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[str] = Field(default_factory=list)
    require_state: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    remote_keywords: list[str] = Field(default_factory=lambda: ["remote", "hybrid"])
    keep_unknown: bool = True
    unknown_patterns: list[str] = Field(
        default_factory=lambda: [r"^\s*$", r"\d+\s+locations?", r"multiple", r"various"]
    )


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: LevelFilter = Field(default_factory=LevelFilter)
    discipline: DisciplineFilter = Field(default_factory=DisciplineFilter)
    location: LocationFilter = Field(default_factory=LocationFilter)


class EmployerFilterOverrides(BaseModel):
    """Per-employer tweaks, e.g. USAJOBS filters by grade/radius server-side."""

    model_config = ConfigDict(extra="forbid")

    skip_level: bool = False
    skip_discipline: bool = False
    skip_location: bool = False
    extra_level_include: list[str] = Field(default_factory=list)


class Employer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: Category
    type: str
    enabled: bool = True
    careers_url: str | None = None
    verified: str | None = None
    notes: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    # None = use settings.respect_robots_txt. Set false only for a site whose
    # robots.txt blocks an endpoint you've decided is fine to use.
    respect_robots_txt: bool | None = None
    filters: EmployerFilterOverrides = Field(default_factory=EmployerFilterOverrides)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(f"employer id must be a slug (letters, digits, - or _): {v!r}")
        return v


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: Settings = Field(default_factory=Settings)
    filters: Filters = Field(default_factory=Filters)
    employers: list[Employer] = Field(default_factory=list)

    @field_validator("employers")
    @classmethod
    def _unique_ids(cls, v: list[Employer]) -> list[Employer]:
        seen: set[str] = set()
        for e in v:
            if e.id in seen:
                raise ValueError(f"duplicate employer id: {e.id}")
            seen.add(e.id)
        return v


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Config.model_validate(data)
