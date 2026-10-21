"""Loopback test servers for the Model Gateway tests: function-scoped, fresh per test."""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest

from ei_ai.model_gateway.gateway import ModelGateway
from model_gateway.fakes import build_gateway
from support.fake_model_server import FakeModelServer, running_fake_model_server
from support.forward_proxy import ForwardProxy, running_forward_proxy


@pytest.fixture
def local_server() -> Iterator[FakeModelServer]:
    """The local llama.cpp stand-in."""
    yield from running_fake_model_server()


@pytest.fixture
def cloud_server() -> Iterator[FakeModelServer]:
    """The cloud provider stand-in (reached only through ``proxy``)."""
    yield from running_fake_model_server()


@pytest.fixture
def proxy() -> Iterator[ForwardProxy]:
    """The egress proxy stand-in."""
    with running_forward_proxy() as running:
        yield running


@pytest.fixture
def other_proxy() -> Iterator[ForwardProxy]:
    """A proxy that environment variables point at; it must never be used."""
    with running_forward_proxy() as running:
        yield running


@pytest.fixture
async def make_gateway() -> AsyncIterator[Callable[..., ModelGateway]]:
    """``fakes.build_gateway`` with every gateway closed after the test."""
    made: list[ModelGateway] = []

    def make(*args: Any, **kwargs: Any) -> ModelGateway:
        gateway = build_gateway(*args, **kwargs)
        made.append(gateway)
        return gateway

    yield make
    for gateway in made:
        await gateway.aclose()
