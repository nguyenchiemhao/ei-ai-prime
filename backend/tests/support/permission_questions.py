"""Test-only corpus for the permission tests: six collections and ten questions (EA-36, R9).

Stand-in for the ten permission questions of EVL-03 until EA-17 lands. Collections, by key:

- ``public``: Public "Company & Careers"
- ``authenticated``: Authenticated "Employee Handbook"
- ``managers``: Restricted ``managers`` "Manager Handbook" (MH)
- ``hr``: Restricted ``hr`` "HR Confidential"
- ``out_of_scope``: Authenticated "Out of scope", readable but never in the scope
- ``other_workspace``: Public, in a second Workspace; it mirrors every topic chunk, so it would be
  the best match for every question if it were ever searched. Its id is listed in the scope.

Each of the first five has one document with an English and a Vietnamese chunk on its topic.
Never imported by ``src``.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from support.fake_embedder import FakeEmbedder
from support.retrieval_corpus import add_collection, add_indexed_document, add_workspace
from support.tenants import OrgRows

PrincipalKey = Literal["anonymous", "authenticated", "managers"]

COLLECTIONS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "public": ("Company & Careers", "public", ()),
    "authenticated": ("Employee Handbook", "authenticated", ()),
    "managers": ("Manager Handbook", "restricted", ("managers",)),
    "hr": ("HR Confidential", "restricted", ("hr",)),
    "out_of_scope": ("Out of scope", "authenticated", ()),
}

TOPIC_TEXTS: dict[str, tuple[str, str]] = {
    "public": (
        "Our office opening hours are 8:00 to 17:30 from Monday to Friday.",
        "Giờ mở cửa văn phòng là từ 8:00 đến 17:30, thứ Hai đến thứ Sáu.",
    ),
    "authenticated": (
        "Every employee gets 14 annual leave days each year.",
        "Mỗi nhân viên có 14 ngày nghỉ phép năm.",
    ),
    "managers": (
        "Salary review bands for managers are set every April.",
        "Khung xét duyệt lương được cập nhật vào tháng Tư.",
    ),
    "hr": (
        "The disciplinary process starts with a written warning.",
        "Quy trình kỷ luật bắt đầu bằng một cảnh cáo bằng văn bản.",
    ),
    "out_of_scope": (
        "Expense claims are paid within ten working days.",
        "Đề nghị hoàn ứng chi phí được thanh toán trong mười ngày làm việc.",
    ),
}

IN_SCOPE = ("public", "authenticated", "managers", "hr")

ALLOWED: dict[PrincipalKey, frozenset[str]] = {
    "anonymous": frozenset({"public"}),
    "authenticated": frozenset({"public", "authenticated"}),
    "managers": frozenset({"public", "authenticated", "managers"}),
}


@dataclass(frozen=True)
class PermissionQuestion:
    question: str
    topic_collection: str
    allowed: dict[PrincipalKey, frozenset[str]]


def _question(question: str, topic: str) -> PermissionQuestion:
    return PermissionQuestion(question, topic, ALLOWED)


PERMISSION_QUESTIONS: tuple[PermissionQuestion, ...] = (
    _question("What are the office opening hours?", "public"),
    _question("How many annual leave days does an employee get?", "authenticated"),
    _question("When are the salary review bands set?", "managers"),
    _question("How does the disciplinary process start?", "hr"),
    _question("How fast are expense claims paid?", "out_of_scope"),
    _question("Giờ mở cửa văn phòng là mấy giờ?", "public"),
    _question("Nhân viên có bao nhiêu ngày nghỉ phép năm?", "authenticated"),
    _question("Khung xét duyệt lương cập nhật khi nào?", "managers"),
    _question("Quy trình kỷ luật bắt đầu như thế nào?", "hr"),
    _question("Đề nghị hoàn ứng chi phí được thanh toán khi nào?", "out_of_scope"),
)


@dataclass(frozen=True)
class PermissionCorpus:
    collections: dict[str, uuid.UUID]  # key -> collection id (all six)
    scope: KnowledgeScope  # the four in-scope collections plus the other Workspace's id

    def key_of(self, collection_id: uuid.UUID) -> str:
        return next(key for key, value in self.collections.items() if value == collection_id)


async def build_permission_corpus(
    conn: AsyncConnection, org: OrgRows, embedder: FakeEmbedder
) -> PermissionCorpus:
    """The six collections, indexed, inside the caller's tenant transaction of ``org``."""
    ids: dict[str, uuid.UUID] = {}
    for key, (name, level, groups) in COLLECTIONS.items():
        collection_id, folder_id = await add_collection(
            conn, org, name=name, access_level=level, groups=groups
        )
        await add_indexed_document(
            conn, org, collection_id, folder_id, TOPIC_TEXTS[key], embedder=embedder
        )
        ids[key] = collection_id
    second = await add_workspace(conn, org, "Second Workspace")
    mirror, mirror_folder = await add_collection(
        conn, org, name="Mirror", access_level="public", workspace_id=second
    )
    mirrored = [text for texts in TOPIC_TEXTS.values() for text in texts]
    await add_indexed_document(conn, org, mirror, mirror_folder, mirrored, embedder=embedder)
    ids["other_workspace"] = mirror
    scope = KnowledgeScope(
        org.workspace_id,
        collection_ids=(*(ids[key] for key in IN_SCOPE), mirror),
    )
    return PermissionCorpus(collections=ids, scope=scope)


FLOOD_QUESTION = "Which visitor parking rules apply at the main gate?"
FLOOD_CHUNKS = 100
PUBLIC_MATCHES = 6


@dataclass(frozen=True)
class FloodCorpus:
    restricted: uuid.UUID  # Restricted ``managers``: 100 chunks equal to the question
    public: uuid.UUID  # Public: 6 chunks that match the question less well
    public_texts: tuple[str, ...]
    scope: KnowledgeScope


async def build_flood_corpus(
    conn: AsyncConnection, org: OrgRows, embedder: FakeEmbedder
) -> FloodCorpus:
    """The AC4 corpus, inside the caller's tenant transaction of ``org``."""
    restricted, r_folder = await add_collection(
        conn, org, name="Flood", access_level="restricted", groups=("managers",)
    )
    await add_indexed_document(
        conn, org, restricted, r_folder, [FLOOD_QUESTION] * FLOOD_CHUNKS, embedder=embedder
    )
    public, p_folder = await add_collection(conn, org, name="Visitors", access_level="public")
    texts = tuple(
        f"Visitor parking rules apply at the main gate, rule {n}." for n in range(PUBLIC_MATCHES)
    )
    await add_indexed_document(conn, org, public, p_folder, texts, embedder=embedder)
    scope = KnowledgeScope(org.workspace_id, collection_ids=(restricted, public))
    return FloodCorpus(restricted=restricted, public=public, public_texts=texts, scope=scope)
