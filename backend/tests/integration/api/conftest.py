"""Fixtures of the API integration tests: the sign-in directory and a signed-in-ready client."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.directory import SignInDirectory
from support.sign_in import auth_client


@pytest.fixture
async def directory() -> AsyncIterator[SignInDirectory]:
    directory = SignInDirectory(os.environ["SIGNIN_DATABASE_URL"])
    try:
        yield directory
    finally:
        await directory.dispose()


@pytest.fixture
async def client(
    app_engine: AsyncEngine, directory: SignInDirectory
) -> AsyncIterator[httpx.AsyncClient]:
    async with auth_client(app_engine, directory) as client:
        yield client
