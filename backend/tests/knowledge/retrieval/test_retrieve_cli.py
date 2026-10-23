"""``ei-ai index retrieve``: parser and argument errors (EA-36). No database is touched: bad
arguments are refused (exit 2) before any setting is read."""

import uuid

import pytest

from ei_ai import cli

ORG = str(uuid.uuid4())
WORKSPACE = str(uuid.uuid4())
BASE = ["index", "retrieve", "--org", ORG, "--workspace", WORKSPACE, "--query", "q"]
AUTH = [*BASE, "--as", "authenticated"]


def test_retrieve_is_registered_with_repeatable_options() -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    argv = [*AUTH, "--group", "a", "--group", "b", "--collection", first, "--folder", second]

    args = cli._parser().parse_args(argv)

    assert (args.command, args.action) == ("index", "retrieve")
    assert args.group == ["a", "b"]
    assert args.collection == [first]
    assert args.folder == [second]
    assert args.k == "4"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            [
                "index",
                "retrieve",
                "--org",
                "nope",
                "--workspace",
                WORKSPACE,
                "--query",
                "q",
                "--as",
                "anonymous",
            ],
            "error: --org must be an Organization id (UUID)",
        ),
        (
            [
                "index",
                "retrieve",
                "--org",
                ORG,
                "--workspace",
                "nope",
                "--query",
                "q",
                "--as",
                "anonymous",
            ],
            "error: --workspace must be a Workspace id (UUID)",
        ),
        ([*AUTH, "--collection", "nope"], "error: --collection must be a collection id (UUID)"),
        ([*AUTH, "--folder", "nope"], "error: --folder must be a folder id (UUID)"),
        ([*AUTH, "--k", "0"], "error: --k must be an integer from 1 to 10"),
        ([*AUTH, "--k", "11"], "error: --k must be an integer from 1 to 10"),
        ([*AUTH, "--k", "many"], "error: --k must be an integer from 1 to 10"),
        (BASE, "error: --as must be anonymous or authenticated"),
        ([*BASE, "--as", "admin"], "error: --as must be anonymous or authenticated"),
        (
            [*BASE, "--as", "anonymous", "--group", "managers"],
            "error: --group needs --as authenticated",
        ),
        ([*AUTH, "--group", ""], "error: --group must be a valid group name (at most 100)"),
        ([*AUTH, "--group", "a,b"], "error: --group must be a valid group name (at most 100)"),
        ([*AUTH, "--group", "x" * 65], "error: --group must be a valid group name (at most 100)"),
        ([*AUTH, "--group", "bad\x07"], "error: --group must be a valid group name (at most 100)"),
        (
            [*AUTH, *[a for i in range(101) for a in ("--group", f"g{i}")]],
            "error: --group must be a valid group name (at most 100)",
        ),
        (
            [
                "index",
                "retrieve",
                "--org",
                ORG,
                "--workspace",
                WORKSPACE,
                "--query",
                "   ",
                "--as",
                "authenticated",
            ],
            "error: --query must be 1 to 2000 characters",
        ),
        (
            [
                "index",
                "retrieve",
                "--org",
                ORG,
                "--workspace",
                WORKSPACE,
                "--query",
                "x" * 2001,
                "--as",
                "authenticated",
            ],
            "error: --query must be 1 to 2000 characters",
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
