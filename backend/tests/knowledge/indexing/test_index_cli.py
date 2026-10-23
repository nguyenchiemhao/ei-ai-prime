"""``ei-ai index``: parsers and argument errors (EA-35 R15, R19). No database is touched: bad
arguments are refused (exit 2) before any setting is read."""

import uuid

import pytest

from ei_ai import cli

ORG = str(uuid.uuid4())
DOCUMENT = str(uuid.uuid4())


@pytest.mark.parametrize(
    "argv",
    [
        ["index", "reindex", "--org", ORG],
        ["index", "reindex", "--org", ORG, "--document", DOCUMENT],
        ["index", "status", "--org", ORG],
        ["index", "search", "--org", ORG, "--query", "nghỉ phép"],
    ],
)
def test_index_commands_are_registered(argv: list[str]) -> None:
    args = cli._parser().parse_args(argv)

    assert (args.command, args.action) == ("index", argv[1])


def test_search_defaults_to_five_hits() -> None:
    args = cli._parser().parse_args(["index", "search", "--org", ORG, "--query", "x"])

    assert args.k == "5"
    assert args.collection is None


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["index", "reindex", "--org", "nope"], "error: --org must be an Organization id (UUID)"),
        (["index", "status", "--org", "nope"], "error: --org must be an Organization id (UUID)"),
        (
            ["index", "search", "--org", "nope", "--query", "x"],
            "error: --org must be an Organization id (UUID)",
        ),
        (
            ["index", "reindex", "--org", ORG, "--document", "nope"],
            "error: --document must be a document id (UUID)",
        ),
        (
            ["index", "status", "--org", ORG, "--document", "nope"],
            "error: --document must be a document id (UUID)",
        ),
        (
            ["index", "search", "--org", ORG, "--query", "x", "--k", "0"],
            "error: --k must be an integer from 1 to 40",
        ),
        (
            ["index", "search", "--org", ORG, "--query", "x", "--k", "41"],
            "error: --k must be an integer from 1 to 40",
        ),
        (
            ["index", "search", "--org", ORG, "--query", "x", "--k", "many"],
            "error: --k must be an integer from 1 to 40",
        ),
        (
            ["index", "search", "--org", ORG, "--query", "x", "--collection", "nope"],
            "error: --collection must be a collection id (UUID)",
        ),
    ],
)
def test_bad_arguments_exit_2_with_the_message(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == 2

    captured = capsys.readouterr()
    assert captured.err.strip() == message
    assert captured.out == ""
