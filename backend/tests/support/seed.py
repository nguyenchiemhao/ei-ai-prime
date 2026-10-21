"""Test-only helpers for the demo seed: variants of the packaged manifests and the seed password.

Never imported by ``src``. A variant has random Organization ids (ascending, like the packaged
ones), suffixed Organization names and its own email domains, so it never meets the real demo
Organizations or another test's rows, not even in the sign-in directory.
"""

import os
import uuid
from pathlib import Path

from ei_ai.seed.manifest import DemoManifest, Member, load_manifests

# The test value of EI_AI_SEED_PASSWORD (never the documented demo value).
TEST_SEED_PASSWORD = "Seed-Test-Value-1"

_REPO_ROOT = Path(os.environ.get("EI_AI_REPO_ROOT", Path(__file__).resolve().parents[3]))


def _read_setting(path: Path) -> str | None:
    """The non-empty EI_AI_SEED_PASSWORD value in a dotenv-style file, or None."""
    if not path.exists():
        return None
    for line in path.read_text("utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "EI_AI_SEED_PASSWORD" and value.strip():
            return value.strip()
    return None


def demo_seed_password() -> str:
    """The value a seed of the real demo Organizations must use, so a test run never gives the
    demo accounts another password than ``npm run seed`` would: the environment variable, then
    ``.env``, then the documented default in ``.env.example``, else the test value."""
    value = os.environ.get("EI_AI_SEED_PASSWORD", "").strip()
    return (
        value
        or _read_setting(_REPO_ROOT / ".env")
        or _read_setting(_REPO_ROOT / ".env.example")
        or TEST_SEED_PASSWORD
    )


def _member_variant(member: Member, suffix: str) -> Member:
    local, domain = member.email.split("@", 1)
    return member.model_copy(update={"email": f"{local}@{suffix}.{domain}"})


def variant_manifests() -> tuple[DemoManifest, ...]:
    """The packaged manifests with ascending random ids, suffixed names and email domains."""
    suffix = uuid.uuid4().hex[:8]
    manifests = load_manifests()
    ids = sorted(uuid.uuid4() for _ in manifests)
    return tuple(
        manifest.model_copy(
            update={
                "organization_id": org_id,
                "organization": f"{manifest.organization} {suffix}",
                "members": [_member_variant(member, suffix) for member in manifest.members],
            }
        )
        for manifest, org_id in zip(manifests, ids, strict=True)
    )
