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
#

"""Test the application logic for verifying user TOTP tokens."""

from contextlib import nullcontext
from typing import cast
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException, status
from ghga_service_commons.utils.utc_dates import now_as_utc
from pydantic import SecretStr
from pytest import mark, raises

from auth_service.auth_adapter.adapters.memory_session_store import MemorySessionStore
from auth_service.auth_adapter.core.session_store import SessionState
from auth_service.auth_adapter.core.totp import TOTPHandler
from auth_service.auth_adapter.core.verify_totp import verify_totp
from auth_service.auth_adapter.ports.dao import UserToken, UserTokenDao
from auth_service.config import Config
from auth_service.user_management.user_registry.models.dto import UserStatus
from auth_service.user_management.user_registry.ports.dao import UserDao

from ...fixtures.utils import DummyUserDao, DummyUserTokenDao

SESSION_ARGS = {
    "ext_id": "john@aai.org",
    "user_name": "John Doe",
    "user_email": "john@home.org",
    "user_id": "john@ghga.de",
}

config = Config(
    totp_encryption_key=SecretStr(TOTPHandler.random_encryption_key()),
)  # pyright: ignore


@mark.asyncio
@mark.parametrize(
    "totp_code",
    ["", "123456", "423715", "123123", "999999"],
    ids=["empty", "invalid", "valid", "rate-limit", "total-limit"],
)
@mark.parametrize(
    "session_state",
    [
        SessionState.REGISTERED,
        SessionState.NEW_TOTP_TOKEN,
        SessionState.HAS_TOTP_TOKEN,
        SessionState.AUTHENTICATED,
    ],
)
async def test_verify_totp(session_state: SessionState, totp_code: str):  # noqa: C901
    """Test the verification of a TOTP code under various circumstances."""
    session_store = MemorySessionStore(config=config)
    session = await session_store.create_session(**SESSION_ARGS)
    session.state = session_state

    user_has_token = session_state in (
        SessionState.HAS_TOTP_TOKEN,
        SessionState.AUTHENTICATED,
    )
    session_has_token = session_state is SessionState.NEW_TOTP_TOKEN
    has_token = user_has_token or session_has_token

    totp_handler = TOTPHandler(config=config)
    totp_token = totp_handler.generate_token() if has_token else None
    if totp_token and totp_code == "999999":  # simulate brute force attack
        totp_token.total_attempts = 10
        assert totp_handler.is_invalid(totp_token)
        limit_reached = True
    else:
        limit_reached = False
    session.totp_token = totp_token

    user_dao = DummyUserDao()
    user_id = user_dao.user.id
    user_token_dao = DummyUserTokenDao()
    if user_has_token:
        assert totp_token
        await user_token_dao.upsert(UserToken(user_id=user_id, totp_token=totp_token))

    if totp_token:
        if totp_code == "423715":
            should_verify = True  # the valid case
        elif totp_code == "123456":
            should_verify = False  # the invalid case
        else:
            should_verify = None  # the totally invalid or rate-limited case
    else:
        should_verify = None  # cannot verify without token

    totp_handler.verify_code = Mock(return_value=should_verify)  # type: ignore

    session_store.save_session = AsyncMock()  # type: ignore
    session_store.delete_session = AsyncMock()  # type: ignore

    with nullcontext() if should_verify else raises(HTTPException) as exc_info:
        await verify_totp(
            totp_code,
            user_id,
            session_store=session_store,
            session=session,
            totp_handler=totp_handler,
            user_dao=cast(UserDao, user_dao),
            token_dao=cast(UserTokenDao, user_token_dao),
        )
    if should_verify:
        assert session.state is SessionState.AUTHENTICATED
        assert session.totp_token is None
    else:
        assert exc_info
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        expected_message = (
            "Too many failed attempts"
            if limit_reached and has_token
            else "Invalid TOTP code"
        )
        assert exc_info.value.detail == expected_message
        assert session.state is session_state
        assert session.totp_token is totp_token

    if limit_reached and user_has_token:
        assert user_dao.user.status is UserStatus.INACTIVE
        status_change = user_dao.user.status_change
        assert status_change
        assert status_change.previous is UserStatus.ACTIVE
        assert status_change.by == user_id
        assert status_change.context == "Too many failed TOTP login attempts"
        assert status_change.change_date
        assert abs((now_as_utc() - status_change.change_date).total_seconds()) < 3
        assert totp_token
        assert not totp_handler.is_invalid(totp_token)
    else:
        assert user_dao.user.status is UserStatus.ACTIVE
        assert not user_dao.user.status_change

    if limit_reached:
        session_store.delete_session.assert_awaited_once()
    else:
        session_store.delete_session.assert_not_called()

    if should_verify or user_has_token:
        assert user_token_dao.user_tokens[user_id].totp_token is totp_token
    else:
        assert not user_token_dao.user_tokens

    if should_verify is not None or (totp_code and not limit_reached and totp_token):
        totp_handler.verify_code.assert_called_once_with(totp_token, totp_code)
    else:
        totp_handler.verify_code.assert_not_called()
    if should_verify is not None:
        session_store.save_session.assert_awaited_once_with(session)
    else:
        session_store.save_session.assert_not_called()
