"""The test question sets keep the promise their docstring makes (EA-37)."""

from support.answer_questions import ANSWERABLE, CORPUS_TEXTS, UNANSWERABLE, words


def test_question_sets_have_the_planned_sizes() -> None:
    assert len(ANSWERABLE) == 6
    assert len(UNANSWERABLE) == 10


def test_unanswerable_questions_share_no_word_with_the_corpus() -> None:
    corpus = set().union(*(words(text) for text in CORPUS_TEXTS))

    assert [q for q in UNANSWERABLE if words(q) & corpus] == []


def test_answerable_questions_share_words_with_a_chunk() -> None:
    for question in ANSWERABLE:
        assert max(len(words(question) & words(text)) for text in CORPUS_TEXTS) >= 4
