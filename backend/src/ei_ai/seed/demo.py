"""Demo seed: the Mekong Devworks manifest, the environment guard and the summary.

FND-04 (EA-21) writes the Organization, Workspace and member rows; until then this entry point
validates the versioned manifest, proves the application role can reach the database and prints
what will be loaded. No table exists yet, so no row is written here (tenant tables need org_id and
RLS from FND-01).
"""

import json
from collections.abc import Callable
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SEED_ENVIRONMENTS = ("local", "test")


class SeedRefused(Exception):
    """The demo seed must not run in this environment."""


class Member(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    email: str = Field(pattern=r"^[a-z0-9.]+@[a-z0-9.]+$")
    roles: list[str] = Field(min_length=1)


class DemoManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[1]
    organization: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    members: list[Member] = Field(min_length=1)

    @model_validator(mode="after")
    def emails_are_unique(self) -> "DemoManifest":
        emails = [member.email for member in self.members]
        if len(set(emails)) != len(emails):
            raise ValueError("member emails must be unique")
        return self


def load_manifest() -> DemoManifest:
    text = resources.files("ei_ai.seed").joinpath("data/mekong-devworks.json").read_text("utf-8")
    return DemoManifest.model_validate(json.loads(text))


def run_demo_seed(environment: str, check_database: Callable[[], None]) -> str:
    """Validate the manifest, check the database and return the summary text.

    Raises SeedRefused outside local/test (before any database access); ``check_database`` raises
    when the database is unreachable.
    """
    if environment not in SEED_ENVIRONMENTS:
        raise SeedRefused(
            f"the demo seed runs only in {' or '.join(SEED_ENVIRONMENTS)} environments"
        )
    manifest = load_manifest()
    check_database()
    lines = [
        f"Demo seed: {manifest.organization}",
        f"  Organization: {manifest.organization}",
        f"  Workspace: {manifest.workspace}",
        f"  Members: {len(manifest.members)}",
        *(f"    - {member.name}: {', '.join(member.roles)}" for member in manifest.members),
        "  Database: reachable as the application role",
        "  Rows: no rows written. FND-04 (EA-21) loads this manifest into the database.",
    ]
    return "\n".join(lines)
