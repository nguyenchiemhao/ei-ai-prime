"""``ei-ai model add`` and ``ei-ai model try`` without a database or a model server (EA-24 AC1,
attack 24): exact output, exit codes, and nothing but the error line on stderr."""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest

from ei_ai import cli
from ei_ai.db import engine as engine_module
from ei_ai.model_gateway import try_command
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import ChatCompleted, ChatMessage, StreamEvent, TextDelta, Usage

DB_PASSWORD = "s3cret-pw"
ORG = "0192a000-0000-7000-8000-00000000ea21"
QWEN = "qwen3-4b-instruct-2507@2026.10"
QWEN_DIGEST = "sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
DONE = re.compile(
    r"^done: model=(\S+)@(\S+) digest=(sha256:[0-9a-f]{12}|none) prompt_tokens=[1-9]\d*"
    r" completion_tokens=[1-9]\d* attempts=[12] first_token_ms=(\d+) total_ms=(\d+)$"
)


@pytest.fixture(autouse=True)
def local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EI_AI_ENV", "local")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://ei_ai_app:{DB_PASSWORD}@db:5432/ei_ai")
    for name in ("MODEL_LOCAL_BASE_URL", "EGRESS_PROXY_URL", "MODEL_READ_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any database access fails the test loudly."""

    class NoDatabaseAccess(Exception):
        pass

    def refuse(url: str) -> None:
        raise NoDatabaseAccess

    monkeypatch.setattr(engine_module, "create_cli_engine", refuse)


class FakeGateway:
    """Stands in for ``ModelGateway.stream_chat``; records how it was called."""

    def __init__(
        self, events: list[StreamEvent] | None = None, error: Exception | None = None
    ) -> None:
        self.events = events if events is not None else []
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.logger_state: tuple[bool, list[str]] | None = None

    async def stream_chat(
        self,
        ctx: ModelCallContext,
        ref: ModelRef,
        messages: list[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        gateway_logger = logging.getLogger("ei_ai.model_gateway")
        self.logger_state = (
            gateway_logger.propagate,
            [type(handler).__name__ for handler in gateway_logger.handlers],
        )
        self.calls.append({"ctx": ctx, "ref": ref, "messages": messages, "max_tokens": max_tokens})
        for event in self.events:
            yield event
        gateway_logger.warning("model call")  # what LoggingObserver does on a failure
        if self.error is not None:
            raise self.error

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_gateway(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeGateway]:
    """Replace the database and the gateway of ``model try``."""

    async def no_db_work(url: str, work: Callable[[Any], Awaitable[Any]]) -> Any:
        return await work(object())

    async def organization_found(engine: object, org_id: uuid.UUID) -> None:
        return None

    def install(**kwargs: Any) -> FakeGateway:
        gateway = FakeGateway(**kwargs)
        monkeypatch.setattr(try_command, "run_with_app_engine", no_db_work)
        monkeypatch.setattr(try_command, "ensure_organization", organization_found)
        monkeypatch.setattr(try_command, "build_gateway", lambda settings, engine: gateway)
        return gateway

    return install


def _completed(digest: str | None = QWEN_DIGEST) -> ChatCompleted:
    return ChatCompleted(QWEN, digest, Usage(7, 2), "stop", 1)


@pytest.mark.parametrize("action", ["add", "try"])
@pytest.mark.parametrize("org", ["not-a-uuid", "", "0192a000"])
def test_bad_org_exits_2_before_any_database_access(
    capsys: pytest.CaptureFixture[str], action: str, org: str
) -> None:
    code = cli.main(["model", action, "--org", org, "--model", QWEN])

    assert code == 2
    captured = capsys.readouterr()
    assert captured.err == "error: --org must be an Organization id (UUID)\n"
    assert captured.out == ""


@pytest.mark.parametrize("action", ["add", "try"])
@pytest.mark.parametrize("model", ["qwen3", "Qwen3@2026.10", "a@b@c", "@1", "http://x/v1@1"])
def test_bad_model_ref_exits_2(capsys: pytest.CaptureFixture[str], action: str, model: str) -> None:
    code = cli.main(["model", action, "--org", ORG, "--model", model])

    assert code == 2
    assert capsys.readouterr().err == "error: --model must be <model_id>@<version>\n"


@pytest.mark.parametrize("value", ["0", "-3", "many"])
def test_bad_max_tokens_exits_2(capsys: pytest.CaptureFixture[str], value: str) -> None:
    code = cli.main(["model", "try", "--org", ORG, "--model", QWEN, "--max-tokens", value])

    assert code == 2
    assert capsys.readouterr().err == "error: --max-tokens must be a positive integer\n"


def test_unexpected_error_prints_the_class_name_only(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["model", "add", "--org", ORG, "--model", QWEN])

    assert code == 1
    err = capsys.readouterr().err
    assert err == "error: model add failed (NoDatabaseAccess)\n"
    assert DB_PASSWORD not in err


def test_try_streams_the_text_then_prints_the_done_line(
    capsys: pytest.CaptureFixture[str], fake_gateway: Callable[..., FakeGateway]
) -> None:
    gateway = fake_gateway(events=[TextDelta("Xin"), TextDelta(" chào"), _completed()])

    code = cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert code == 0
    captured = capsys.readouterr()
    text, _, last = captured.out.rstrip("\n").rpartition("\n")
    assert text == "Xin chào"
    match = DONE.match(last)
    assert match is not None, last
    assert last.startswith(
        f"done: model={QWEN} digest=sha256:3605803b982c prompt_tokens=7 completion_tokens=2"
        " attempts=1 "
    )
    assert int(match.group(4)) <= int(match.group(5))
    assert captured.err == ""
    assert gateway.closed


def test_try_sends_the_default_prompt_and_max_tokens_as_the_platform_operator(
    fake_gateway: Callable[..., FakeGateway],
) -> None:
    gateway = fake_gateway(events=[TextDelta("x"), _completed()])

    cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    [call] = gateway.calls
    assert call["ctx"] == ModelCallContext(org_id=uuid.UUID(ORG), actor="platform-operator")
    assert call["ref"] == ModelRef.parse(QWEN)
    assert call["messages"] == [ChatMessage("user", "Xin chào, hãy giới thiệu ngắn gọn về bạn.")]
    assert call["max_tokens"] == 64


def test_try_takes_the_prompt_and_max_tokens_options(
    fake_gateway: Callable[..., FakeGateway],
) -> None:
    gateway = fake_gateway(events=[TextDelta("x"), _completed()])
    argv = ["model", "try", "--org", ORG, "--model", QWEN, "--prompt", "Hi", "--max-tokens", "16"]

    cli.main(argv)

    assert gateway.calls[0]["messages"] == [ChatMessage("user", "Hi")]
    assert gateway.calls[0]["max_tokens"] == 16


def test_cloud_rows_print_digest_none(
    capsys: pytest.CaptureFixture[str], fake_gateway: Callable[..., FakeGateway]
) -> None:
    fake_gateway(events=[TextDelta("x"), _completed(digest=None)])

    cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert " digest=none " in capsys.readouterr().out


@pytest.mark.parametrize("code", list(ModelErrorCode))
def test_errors_print_code_line_only(
    capsys: pytest.CaptureFixture[str],
    fake_gateway: Callable[..., FakeGateway],
    code: ModelErrorCode,
) -> None:
    error = ModelError(code, QWEN)
    gateway = fake_gateway(error=error)

    exit_code = cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert exit_code == 1
    assert capsys.readouterr().err == f"error: {code.value}: {error}\n"
    assert gateway.closed


def test_stderr_has_no_log_lines(
    capsys: pytest.CaptureFixture[str], fake_gateway: Callable[..., FakeGateway]
) -> None:
    gateway = fake_gateway(error=ModelError(ModelErrorCode.MODEL_UNAVAILABLE, QWEN))

    cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert capsys.readouterr().err == f"error: MODEL_UNAVAILABLE: model {QWEN} is unavailable\n"
    # While the command runs the metadata line goes nowhere (never to Python's last-resort
    # handler on stderr); afterwards the logger is as it was.
    assert gateway.logger_state == (False, ["NullHandler"])
    gateway_logger = logging.getLogger("ei_ai.model_gateway")
    assert gateway_logger.propagate is True
    assert gateway_logger.handlers == []


def test_text_already_streamed_ends_with_a_newline_before_an_error(
    capsys: pytest.CaptureFixture[str], fake_gateway: Callable[..., FakeGateway]
) -> None:
    fake_gateway(
        events=[TextDelta("Xin")], error=ModelError(ModelErrorCode.MODEL_UNAVAILABLE, QWEN)
    )

    code = cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == "Xin\n"
    assert captured.err == f"error: MODEL_UNAVAILABLE: model {QWEN} is unavailable\n"


def test_try_unexpected_error_prints_the_class_name_only(
    capsys: pytest.CaptureFixture[str], fake_gateway: Callable[..., FakeGateway]
) -> None:
    fake_gateway(error=RuntimeError(f"postgresql://ei_ai_app:{DB_PASSWORD}@db/ei_ai"))

    code = cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert code == 1
    assert capsys.readouterr().err == "error: model try failed (RuntimeError)\n"


def test_try_bad_model_settings_is_a_configuration_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_LOCAL_BASE_URL", "ftp://model")

    code = cli.main(["model", "try", "--org", ORG, "--model", QWEN])

    assert code == 1
    assert capsys.readouterr().err == (
        "configuration error: MODEL_LOCAL_BASE_URL must be an http or https URL\n"
    )
