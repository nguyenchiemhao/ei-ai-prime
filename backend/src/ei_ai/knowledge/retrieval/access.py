"""The read rule of a principal, as a function and as the vector filter (fail closed).

Anonymous reads ``public``; authenticated reads ``public`` and ``authenticated``; a restricted
entry is readable only through a shared group. ``restricted`` is never an allowed level.
"""

from collections.abc import Sequence
from uuid import UUID

from ei_ai.knowledge.retrieval.principal import AnonymousPrincipal, RetrievalPrincipal
from ei_ai.vectors.search import VectorFilter

_ANONYMOUS_LEVELS = ("public",)
_AUTHENTICATED_LEVELS = ("public", "authenticated")


def _levels_and_groups(principal: RetrievalPrincipal) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if isinstance(principal, AnonymousPrincipal):
        return _ANONYMOUS_LEVELS, ()
    return _AUTHENTICATED_LEVELS, principal.groups


def can_read(principal: RetrievalPrincipal, access_level: str, groups: Sequence[str]) -> bool:
    levels, own_groups = _levels_and_groups(principal)
    return access_level in levels or not set(own_groups).isdisjoint(groups)


def permission_filter(
    principal: RetrievalPrincipal,
    collection_ids: tuple[UUID, ...],
    folder_ids: tuple[UUID, ...],
) -> VectorFilter:
    """The filter for ``nearest``. Empty scopes stay empty (match nothing), never None."""
    levels, groups = _levels_and_groups(principal)
    return VectorFilter(
        collection_ids=collection_ids,
        access_levels=levels,
        groups=groups,
        folder_ids=folder_ids,
    )
