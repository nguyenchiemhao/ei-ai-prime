"""Ask a collection (EA-37): ``POST .../collections/{id}/ask`` streams a grounded answer.

The Organization, Workspace and caller come from the verified session and the path only (D32,
D46); the body carries the question and the *simulated* reader (``principal``) the answer is
checked for, never an id (extra fields are refused). Retrieval runs in the tenant transaction,
which commits when the route function returns; the model is called afterwards, while the stream
is sent, and touches no database session. Nothing is written (R15). Error responses and the
``error`` frame are codes only, and nothing here logs: a question, an answer or a group must not
reach a log (D52).

Check order (R34): CSRF, session, Workspace visibility and permission, body, group names,
collection, models.
"""

import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator

from ei_ai.api.deps import TenantSession
from ei_ai.knowledge import service
from ei_ai.knowledge.answers.events import (
    AnswerDelta,
    AnswerDone,
    AnswerEvent,
    AnswerFailed,
    PassagesFound,
)
from ei_ai.knowledge.answers.service import prepare_answer, stream_answer
from ei_ai.knowledge.errors import CollectionNotFound, InvalidGroup
from ei_ai.knowledge.retrieval.principal import MAX_PRINCIPAL_GROUPS, simulated_principal
from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError
from ei_ai.rbac.access import WorkspaceAccess
from ei_ai.rbac.declarations import requires
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext, require_tenant

router = APIRouter()

MAX_QUESTION_CHARS = 2000
SCORE_DECIMALS = 4


class AskPrincipal(BaseModel):
    """Who the answer is checked for. ``groups`` are validated by ``simulated_principal`` (up to
    100 distinct names); the route refuses more than 100 items before normalising them."""

    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal["anonymous", "authenticated"]
    groups: list[str] = []


class AskRequest(BaseModel):
    """Only these fields: an ``org_id``, ``user_id`` or ``workspace_id`` is a 422."""

    model_config = ConfigDict(strict=True, extra="forbid")

    question: str
    principal: AskPrincipal

    @field_validator("question")
    @classmethod
    def _question_length(cls, value: str) -> str:
        if not 1 <= len(value.strip()) <= MAX_QUESTION_CHARS:
            raise ValueError("question length")
        return value


class EventStream(StreamingResponse):
    """A Server-Sent Events response (OpenAPI shows ``text/event-stream``)."""

    media_type = "text/event-stream"


def _frame(event: AnswerEvent) -> str:
    """One SSE frame: ``event: <name>`` and a one-line JSON ``data`` (contract "API")."""
    name: str
    data: dict[str, Any]
    match event:
        case PassagesFound():
            name = "passages"
            data = {
                "language": event.language,
                "passages": [
                    {
                        "number": p.number,
                        "title": p.title,
                        "section": p.section,
                        "page": p.page,
                        "score": round(p.score, SCORE_DECIMALS),
                    }
                    for p in event.passages
                ],
            }
        case AnswerDelta():
            name, data = "delta", {"text": event.text}
        case AnswerDone():
            name = "done"
            data = {
                "outcome": event.outcome,
                "answer": event.answer,
                "citations": list(event.citations),
            }
        case AnswerFailed():
            name, data = "error", {"code": event.code}
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _frames(events: AsyncGenerator[AnswerEvent]) -> AsyncIterator[str]:
    """The frames of an answer; the answer stream is closed when the client goes away."""
    async with aclosing(events) as stream:
        async for event in stream:
            yield _frame(event)


def _error(description: str) -> dict[str, Any]:
    """An error response in JSON: with a custom ``response_class`` FastAPI would otherwise list
    the ``model`` under the event-stream media type."""
    return {
        "description": description,
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorCode"}},
        },
    }


_UNAUTHENTICATED = _error("No live session (unauthenticated)")
_FORBIDDEN = _error("The role lacks the permission (forbidden)")
_NOT_FOUND = _error("Unknown or invisible Workspace or collection (not_found)")
_INVALID = _error(
    "Malformed request, identity field or unacceptable value (invalid_request, invalid_group)"
)
_UNAVAILABLE = _error("The embedding or answer model is not available (model_unavailable)")
_STREAM = {
    "description": "Server-Sent Events: passages, delta (0..n), then done or error",
    "content": {"text/event-stream": {"schema": {"type": "string"}}},
}

ManageAccess = Annotated[WorkspaceAccess, Depends(requires(Permission.KNOWLEDGE_MANAGE))]
Tenant = Annotated[TenantContext, Depends(require_tenant)]


@router.post(
    "/workspaces/{workspace_id}/collections/{collection_id}/ask",
    response_class=EventStream,
    responses={
        200: _STREAM,
        401: _UNAUTHENTICATED,
        403: _FORBIDDEN,
        404: _NOT_FOUND,
        422: _INVALID,
        503: _UNAVAILABLE,
    },
    summary="Ask a collection a question and stream the cited answer",
)
async def ask_collection(
    collection_id: uuid.UUID,
    body: AskRequest,
    request: Request,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> EventStream:
    # A cheap cap before normalising every entry (R32): more than 100 items is never acceptable.
    if len(body.principal.groups) > MAX_PRINCIPAL_GROUPS:
        raise HTTPException(status_code=422, detail="invalid_group")
    try:
        principal = simulated_principal(body.principal.kind, body.principal.groups)
    except InvalidGroup:
        raise HTTPException(status_code=422, detail="invalid_group") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_request") from None
    conn = await session.connection()
    try:
        await service.get_collection(conn, tenant, access, collection_id)
    except CollectionNotFound:
        raise HTTPException(status_code=404, detail="not_found") from None

    state = request.app.state
    embedder, model = state.embedder, state.answer_model
    if embedder is None or model is None:
        raise HTTPException(status_code=503, detail="model_unavailable")
    ctx = ModelCallContext.from_tenant(tenant)
    try:
        prepared = await prepare_answer(
            session,
            tenant,
            body.question,
            principal,
            KnowledgeScope(access.workspace_id, (collection_id,), ()),
            embedder=embedder,
            ctx=ctx,
            reranker=state.reranker,
        )
    except ModelError:
        raise HTTPException(status_code=503, detail="model_unavailable") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_request") from None
    return EventStream(
        _frames(stream_answer(prepared, model=model, ctx=ctx)),
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
