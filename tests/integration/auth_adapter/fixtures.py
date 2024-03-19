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
from typing import NamedTuple, Optional

from fastapi import status
from ghga_service_commons.api.testing import AsyncTestClient
from ghga_service_commons.utils.utc_dates import now_as_utc
from httpx import Response
from pydantic import SecretStr
from pytest import fixture
from pytest_asyncio import fixture as async_fixture
from pytest_httpx import HTTPXMock

from auth_service.auth_adapter.core.session_store import Session
from auth_service.auth_adapter.core.totp import TOTPHandler
from auth_service.auth_adapter.deps import get_user_token_dao
from auth_service.deps import Config, get_config
from auth_service.user_management.claims_repository.deps import get_claim_dao
from auth_service.user_management.user_registry.deps import (
    get_iva_dao,
    get_user_dao,
    get_user_registry,
)

from ...fixtures.utils import (
    RE_USER_INFO_URL,
    USER_INFO,
    DummyClaimDao,
    DummyUserRegistry,
    DummyUserTokenDao,
    create_access_token,
    headers_for_session,
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
    user_registry: DummyUserRegistry
    user_token_dao: DummyUserTokenDao


_map_session_dict_to_object = {
    "ext_id": "ext_id",
    "id": "user_id",
    "name": "user_name",
    "email": "user_email",
    "title": "user_title",
    "role": "role",
    "csrf": "csrf_token",
}


def session_from_response(
    response: Response, session_id: Optional[str] = None
) -> Session:
    """Get a session object from the response."""
    if not session_id:
        session_id = response.cookies.get("session")
        assert session_id
    session_header = response.headers.get("X-Session")
    assert session_header
    session_dict = json.loads(session_header)
    for key, attr in _map_session_dict_to_object.items():
        session_dict[attr] = session_dict.pop(key, None)
    now = now_as_utc()
    last_used = now - timedelta(seconds=session_dict.pop("timeout", 0))
    created = last_used - timedelta(seconds=session_dict.pop("extends", 0))
    session_dict.update(last_used=last_used, created=created)
    session = Session(session_id=session_id, **session_dict)
    assert session.totp_token is None  # should never be passed to the client
    return session


async def query_new_session(
    client: AsyncTestClient, session: Optional[Session] = None
) -> Session:
    """Query the current backend session."""
    if session:
        headers = headers_for_session(session)
    else:
        auth = f"Bearer {create_access_token()}"
        headers = {"Authorization": auth}
    response = await client.post("/rpc/login", headers=headers)
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert "X-CSRF-Token" not in response.headers
    if session:
        assert "session" not in response.cookies
        session_id = session.session_id
    else:
        session_id = response.cookies.get("session")
        assert session_id
    session_header = response.headers.get("X-Session")
    assert session_header
    session_dict = json.loads(session_header)
    for key, attr in _map_session_dict_to_object.items():
        session_dict[attr] = session_dict.pop(key, None)
    now = now_as_utc()
    last_used = now - timedelta(seconds=session_dict.pop("timeout", 0))
    created = last_used - timedelta(seconds=session_dict.pop("extends", 0))
    session_dict.update(last_used=last_used, created=created)
    session = Session(session_id=session_id, **session_dict)
    assert session.totp_token is None  # should never be passed to the client
    return session


@async_fixture(name="client_with_session")
async def fixture_client_with_session(
    client: AsyncTestClient, httpx_mock: HTTPXMock
) -> AsyncGenerator[ClientWithSession, None]:
    """Get test client for the auth adapter with a logged in user"""
    from auth_service.auth_adapter.api import main

    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_registry = DummyUserRegistry()
    user_dao = user_registry.dummy_user_dao
    iva_dao = user_registry.dummy_iva_dao
    user_token_dao = DummyUserTokenDao()
    claim_dao = DummyClaimDao()

    overrides = main.app.dependency_overrides
    overrides[get_user_dao] = lambda: user_dao
    overrides[get_iva_dao] = lambda: iva_dao
    overrides[get_user_registry] = lambda: user_registry
    overrides[get_user_token_dao] = lambda: user_token_dao
    overrides[get_claim_dao] = lambda: claim_dao

    session = await query_new_session(client)

    yield ClientWithSession(client, session, user_registry, user_token_dao)


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
