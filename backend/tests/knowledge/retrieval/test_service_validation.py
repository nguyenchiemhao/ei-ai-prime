"""EA-36: ``retrieve`` refuses a bad question or ``k`` before any model call or statement."""

import uuid
from typing import Any

import pytest

from ei_ai.knowledge.retrieval import service
from ei_ai.knowledge.retrieval.principal import AnonymousPrincipal
from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.tenancy.context import TenantContext
from support.fake_embedder import FakeEmbedder

TENANT = TenantContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())
CTX = ModelCallContext(org_id=TENANT.org_id, actor="platform-operator")
SCOPE = KnowledgeScope(uuid.uuid4(), collection_ids=(uuid.uuid4(),))


class _NoSession:
    """Any database use fails the test."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"session.{name} used before validation")


def test_limits() -> None:
    assert service.CANDIDATES == 20
    assert service.DEFAULT_K == 4
    assert service.MAX_K == 10
    assert service.MAX_QUESTION_CHARS == 2000


@pytest.mark.parametrize(
    ("question", "k"),
    [
        ("", 4),
        ("   \n\t ", 4),
        ("x" * 2001, 4),
        ("ok", 0),
        ("ok", 11),
        ("ok", True),
        ("ok", 4.0),
    ],
    ids=["empty", "whitespace", "too-long", "k-0", "k-11", "k-bool", "k-float"],
)
async def test_bad_question_or_k_is_refused_before_the_embedder(question: str, k: Any) -> None:
    embedder = FakeEmbedder()
    with pytest.raises(ValueError):
        await service.retrieve(
            _NoSession(),  # type: ignore[arg-type]
            TENANT,
            question,
            AnonymousPrincipal(),
            SCOPE,
            embedder=embedder,
            ctx=CTX,
            k=k,
        )
    assert embedder.calls == []


async def test_limits_are_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2000-character question (after trimming) and k = 1 and 10 pass validation."""
    reached: list[int] = []

    async def stop(*args: Any, **kwargs: Any) -> Any:
        reached.append(1)
        raise RuntimeError("stop after validation")

    monkeypatch.setattr(service, "embed_query", stop)
    for question, k in ((" " + "x" * 2000 + " ", 4), ("ok", 1), ("ok", 10)):
        with pytest.raises(RuntimeError):
            await service.retrieve(
                _NoSession(),  # type: ignore[arg-type]
                TENANT,
                question,
                AnonymousPrincipal(),
                SCOPE,
                embedder=FakeEmbedder(),
                ctx=CTX,
                k=k,
            )
    assert reached == [1, 1, 1]
