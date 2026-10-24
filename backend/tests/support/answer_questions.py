"""Test-only corpus and questions for the answer tests (EA-37, R17).

Stand-in for the answerable and unanswerable questions of EVL-03 until EA-17 lands. Three
collections: Public "Company & Careers", Authenticated "Employee Handbook" and Restricted
``managers`` "Manager Handbook", each with one document with headings. ``ANSWERABLE`` (6, three
Vietnamese and three English) share words with one chunk of the Public or Authenticated
collections; ``UNANSWERABLE`` (10) share no word with any chunk. With ``FakeEmbedder`` (bag of
words) that makes the first score well above ``MIN_RELEVANCE`` and the second score zero.

Never imported by ``src``.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from support.fake_embedder import FakeEmbedder
from support.retrieval_corpus import add_collection, add_indexed_document
from support.tenants import OrgRows

# (key, collection name, access level, groups, document name, [(heading path, chunk text)])
_DOCUMENTS: tuple[
    tuple[str, str, str, tuple[str, ...], str, tuple[tuple[tuple[str, ...], str], ...]], ...
] = (
    (
        "public",
        "Company & Careers",
        "public",
        (),
        "Office Hours.md",
        (
            (
                ("Office Hours", "Opening hours"),
                "Our office is open from 8:00 to 17:30 Monday to Friday",
            ),
            (
                ("Office Hours", "Opening hours"),
                "Văn phòng mở cửa từ 8:00 đến 17:30 thứ Hai đến thứ Sáu",
            ),
        ),
    ),
    (
        "authenticated",
        "Employee Handbook",
        "authenticated",
        (),
        "Leave Policy 2026.md",
        (
            (
                ("Leave Policy 2026", "§2 Annual leave"),
                "Every employee gets 12 days of paid annual leave per year",
            ),
            (
                ("Leave Policy 2026", "§2 Annual leave"),
                "Mỗi nhân viên được 12 ngày nghỉ phép năm hưởng lương",
            ),
            (
                ("Leave Policy 2026", "§4.1 Personal leave"),
                "Employees get 3 days of paid leave when they marry",
            ),
            (
                ("Leave Policy 2026", "§4.1 Personal leave"),
                "Nhân viên được nghỉ 3 ngày hưởng nguyên lương khi kết hôn",
            ),
            (
                ("Leave Policy 2026", "§4.3 Bereavement leave"),
                "Employees get 3 days of paid leave when a parent, spouse or child dies",
            ),
        ),
    ),
    (
        "managers",
        "Manager Handbook",
        "restricted",
        ("managers",),
        "Salary Review.md",
        (
            (
                ("Salary Review", "Review cycle"),
                "Salary bands are reviewed every April by the managers committee",
            ),
            (("Salary Review", "Review cycle"), "Khung lương được xem xét vào tháng Tư hằng năm"),
        ),
    ),
)

CORPUS_TEXTS: tuple[str, ...] = tuple(text for *_, chunks in _DOCUMENTS for _, text in chunks)

ANSWERABLE: tuple[str, ...] = (
    "Kết hôn được nghỉ mấy ngày?",
    "Nghỉ phép năm được bao nhiêu ngày?",
    "Văn phòng mở cửa từ mấy giờ?",
    "How many days of paid leave do employees get when they marry?",
    "How many days of annual leave does every employee get per year?",
    "What time is the office open Monday to Friday?",
)

UNANSWERABLE: tuple[str, ...] = (
    "Which city hosts Australian parliament?",
    "Who invented telephones?",
    "How can I reset my VPN token?",
    "Who assists chief executive daily?",
    "Unused vacation carry forward policy?",
    "Căng tin bán món chay không?",
    "Giá cổ phiếu hôm nay bao nhiêu?",
    "Chính sách thưởng Tết thế nào?",
    "Công ty hỗ trợ học phí MBA không?",
    "Mang thú cưng chỗ làm không?",
)

_WORD = re.compile(r"\w+")


def words(text: str) -> set[str]:
    """The lower-cased word tokens ``FakeEmbedder`` counts."""
    return set(_WORD.findall(text.lower()))


@dataclass(frozen=True)
class AnswerCorpus:
    collections: dict[str, uuid.UUID]  # key (public, authenticated, managers) -> collection id
    scope: KnowledgeScope  # all three collections

    def key_of(self, collection_id: uuid.UUID) -> str:
        return next(key for key, value in self.collections.items() if value == collection_id)


async def build_answer_corpus(
    conn: AsyncConnection, org: OrgRows, embedder: FakeEmbedder
) -> AnswerCorpus:
    """The three collections, indexed, inside the caller's tenant transaction of ``org``."""
    ids: dict[str, uuid.UUID] = {}
    for key, name, level, groups, document, chunks in _DOCUMENTS:
        collection_id, folder_id = await add_collection(
            conn, org, name=name, access_level=level, groups=groups
        )
        await add_indexed_document(
            conn,
            org,
            collection_id,
            folder_id,
            [text for _, text in chunks],
            embedder=embedder,
            name=document,
            headings=[heading for heading, _ in chunks],
        )
        ids[key] = collection_id
    scope = KnowledgeScope(org.workspace_id, collection_ids=tuple(ids.values()))
    return AnswerCorpus(collections=ids, scope=scope)
