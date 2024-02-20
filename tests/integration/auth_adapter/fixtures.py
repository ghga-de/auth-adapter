# Copyright 2021 - 2023 Universität Tübingen, DKFZ, EMBL, and Universität zu Köln
# for the German Human Genome-Phenome Archive (GHGA)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Fixtures for the auth adapter integration tests"""

import json
from collections.abc import AsyncGenerator, Generator
from datetime import timedelta
from importlib import reload
from os import environ
from typing import NamedTuple

from fastapi import status
from ghga_service_commons.api.testing import AsyncTestClient
from ghga_service_commons.utils.utc_dates import now_as_utc
from pydantic import SecretStr
from pytest import fixture
from pytest_asyncio import fixture as async_fixture
from pytest_httpx import HTTPXMock

from auth_service.auth_adapter.core.session_store import Session
from auth_service.auth_adapter.core.totp import TOTPHandler
from auth_service.deps import Config, get_config
from auth_service.user_management.user_registry.deps import get_user_dao

from ...fixtures.utils import (
    RE_USER_INFO_URL,
    USER_INFO,
    DummyUserDao,
    create_access_token,
)

totp_encryption_key = TOTPHandler.random_encryption_key()


@async_fixture(name="client")
async def fixture_client() -> AsyncGenerator[AsyncTestClient, None]:
    """Get test client for the auth adapter"""
    from auth_service.auth_adapter.api import main

    reload(main)

    config_with_totp_encryption_key = Config(
        totp_encryption_key=SecretStr(totp_encryption_key),
    )  # pyright: ignore
    main.app.dependency_overrides[get_config] = lambda: config_with_totp_encryption_key

    async with AsyncTestClient(main.app) as client:
        yield client


class ClientWithSession(NamedTuple):
    """A test client with a client session."""

    client: AsyncTestClient
    session: Session


_map_session_dict_to_object = {
    "userId": "user_id",
    "name": "user_name",
    "email": "user_email",
    "csrf": "csrf_token",
}


@async_fixture(name="client_with_session")
async def fixture_client_with_session(
    client: AsyncTestClient, httpx_mock: HTTPXMock
) -> AsyncGenerator[ClientWithSession, None]:
    """Get test client for the auth adapter with a logged in user"""
    from auth_service.auth_adapter.api import main

    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao()
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao

    auth = f"Bearer {create_access_token()}"
    response = await client.post("/rpc/login", headers={"Authorization": auth})
    assert response.status_code == status.HTTP_204_NO_CONTENT

    auth = f"Bearer {create_access_token()}"
    response = await client.post("/rpc/login", headers={"Authorization": auth})
    assert response.status_code == status.HTTP_204_NO_CONTENT
    session_id = response.cookies.get("session")
    assert session_id
    session_header = response.headers.get("X-Session")
    assert session_header
    session_dict = json.loads(session_header)
    for key, attr in _map_session_dict_to_object.items():
        session_dict[attr] = session_dict.pop(key, None)
    expires = session_dict.pop("expires", 0)
    last_used = now_as_utc()
    created = last_used - timedelta(seconds=expires)
    session_dict.update(last_used=last_used, created=created)
    session = Session(session_id=session_id, **session_dict)
    yield ClientWithSession(client, session)


@fixture(name="with_basic_auth")
def fixture_with_basic_auth() -> Generator[str, None, None]:
    """Run test with Basic authentication"""
    from auth_service import config
    from auth_service.auth_adapter.api import main

    user, pwd = "testuser", "testpwd"
    credentials = f"{user}:{pwd}"
    environ["AUTH_SERVICE_BASIC_AUTH_CREDENTIALS"] = credentials
    environ["AUTH_SERVICE_ALLOW_READ_PATHS"] = '["/allowed/read/*", "/logo.png"]'
    environ["AUTH_SERVICE_ALLOW_WRITE_PATHS"] = '["/allowed/write/*"]'
    reload(config)
    reload(main)
    yield credentials
    del environ["AUTH_SERVICE_BASIC_AUTH_CREDENTIALS"]
    del environ["AUTH_SERVICE_ALLOW_READ_PATHS"]
    del environ["AUTH_SERVICE_ALLOW_WRITE_PATHS"]
    reload(config)
    reload(main)
