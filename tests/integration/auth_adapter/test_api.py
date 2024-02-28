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

"""Test the api module"""

import re
from base64 import b64encode
from typing import cast

from fastapi import status
from ghga_service_commons.api.testing import AsyncTestClient
from ghga_service_commons.utils.utc_dates import now_as_utc
from pytest import fixture, mark
from pytest_httpx import HTTPXMock

from auth_service.auth_adapter.api import main
from auth_service.auth_adapter.api.headers import get_bearer_token
from auth_service.config import CONFIG
from auth_service.user_management.claims_repository.deps import ClaimDao, get_claim_dao
from auth_service.user_management.user_registry.deps import UserDao, get_user_dao
from auth_service.user_management.user_registry.models.dto import UserStatus

from ...fixtures.utils import (
    DummyClaimDao,
    DummyUserDao,
    create_access_token,
    get_claims_from_token,
    headers_for_session,
)
from .fixtures import (  # noqa: F401
    ClientWithSession,
    fixture_client,
    fixture_client_with_session,
    fixture_with_basic_auth,
    query_new_session,
)

API_EXT_PATH = CONFIG.api_ext_path.strip("/")
if API_EXT_PATH:
    API_EXT_PATH += "/"
USERS_PATH = f"/{API_EXT_PATH}users"

USER_INFO = {
    "name": "John Doe",
    "email": "john@home.org",
    "sub": "john@aai.org",
}
RE_USER_INFO_URL = re.compile(".*/userinfo$")


@fixture
def non_mocked_hosts() -> list:
    """Do not mock requests to the test server."""
    return ["testserver"]


@mark.asyncio
async def test_get_from_root(client: AsyncTestClient):
    """Test that a simple GET request passes."""
    response = await client.get("/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_get_from_some_path(client: AsyncTestClient):
    """Test that a simple GET request passes."""
    response = await client.get("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_get_from_some_path_with_query_parameters(client: AsyncTestClient):
    """Test that a simple GET request passes."""
    response = await client.get("/some/path?foo=1&bar=2")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_patch_to_some_path(client: AsyncTestClient):
    """Test that a PATCH request to a random path passes."""
    response = await client.patch("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_post_to_some_path(client: AsyncTestClient):
    """Test that a POST request to a random path passes."""
    response = await client.post("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_delete_to_some_path(client: AsyncTestClient):
    """Test that a DELETE request to a random path passes."""
    response = await client.delete("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_basic_auth(with_basic_auth: str, client: AsyncTestClient):
    """Test that the root path can be protected with basic authentication."""
    response = await client.get("/")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == 'Basic realm="GHGA Data Portal"'
    assert response.text == "GHGA Data Portal: Not authenticated"

    auth = b64encode(b"bad:credentials").decode("ASCII")
    auth = f"Basic {auth}"
    response = await client.get("/", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == 'Basic realm="GHGA Data Portal"'
    assert response.text == "GHGA Data Portal: Incorrect username or password"

    auth = b64encode(with_basic_auth.encode("UTF-8")).decode("ASCII")
    auth = f"Basic {auth}"
    response = await client.get("/", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}


@mark.asyncio
async def test_allowed_paths(with_basic_auth: str, client: AsyncTestClient):
    """Test that allowed paths are excluded from authentication."""
    assert with_basic_auth

    response = await client.get(
        "/allowed/read/some/thing", headers={"Authorization": "Bearer foo"}
    )
    # access should be allowed without basic authentication
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}
    # and authorization headers should be passed through
    assert response.headers["Authorization"] == "Bearer foo"

    response = await client.head("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await client.options("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await client.post(
        "/allowed/write/some/thing", headers={"Authorization": "Bearer bar"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}
    assert response.headers["Authorization"] == "Bearer bar"

    response = await client.patch("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await client.delete("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await client.post("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == "GHGA Data Portal: Not authenticated"

    response = await client.delete("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = await client.get("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == "GHGA Data Portal: Not authenticated"

    response = await client.options("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = await client.post("/not-allowed/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == "GHGA Data Portal: Not authenticated"


@mark.asyncio
async def test_basic_auth_service_logo(with_basic_auth: str, client: AsyncTestClient):
    """Test that fetching the service logo is excluded from authentication."""
    assert with_basic_auth

    response = await client.get("/logo.png")
    assert response.status_code == status.HTTP_200_OK

    response = await client.head("/logo.png")
    assert response.status_code == status.HTTP_200_OK

    response = await client.get("/image.png")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = await client.head("/image.png")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@mark.asyncio
async def test_does_not_authorize_invalid_users(client: AsyncTestClient):
    """Test that unauthenticated or invalid users are not authorized."""
    # User without Authorization token
    response = await client.get("/some/path")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert "Authorization" in headers
    assert headers["Authorization"] == ""
    assert "X-Authorization" not in headers

    # User with empty Authorization token
    response = await client.get("/some/path", headers={"Authorization": ""})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert "Authorization" in headers
    assert headers["Authorization"] == ""
    assert "X-Authorization" not in headers

    # User with non-bearer Authorization token
    response = await client.get("/some/path", headers={"Authorization": "Foo bar"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert "Authorization" in headers
    assert headers["Authorization"] == ""
    assert "X-Authorization" not in headers

    # User with empty bearer Authorization token
    response = await client.get("/some/path", headers={"Authorization": "Bearer"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert "Authorization" in headers
    assert headers["Authorization"] == ""
    assert "X-Authorization" not in headers

    # User with invalid bearer Authorization token
    response = await client.get(
        "/some/path", headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid access token"}

    headers = response.headers
    assert "Authorization" not in headers
    assert "X-Authorization" not in headers

    # User with invalid bearer X-Authorization token
    response = await client.get(
        "/some/path", headers={"Authorization": "Bearer invalid"}
    )
    response = await client.get(
        "/some/path",
        headers={"Authorization": "Basic invalid", "X-Authorization": "Bearer invalid"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid access token"}

    headers = response.headers
    assert "Authorization" not in headers
    assert "X-Authorization" not in headers


@mark.asyncio
async def test_token_exchange_for_unknown_user(
    client: AsyncTestClient, httpx_mock: HTTPXMock
):
    """Test the token exchange for authenticated but unknown users."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao(ext_id="not.john@aai.org")
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao

    auth = f"Bearer {create_access_token()}"

    # does not get internal token for GET request to random path
    response = await client.get("/some/path", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert headers.get("Authorization") == ""
    assert "X-Authorization" not in headers

    # does not get internal token for POST request to random path
    response = await client.post("/some/path", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert headers.get("Authorization") == ""
    assert "X-Authorization" not in headers

    # does not get internal token for GET request to users
    response = await client.get(USERS_PATH, headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert headers.get("Authorization") == ""
    assert "X-Authorization" not in headers

    # does not get internal token for GET request to users with internal ID
    response = await client.get(
        f"{USERS_PATH}/some-internal-id", headers={"Authorization": auth}
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert headers.get("Authorization") == ""
    assert "X-Authorization" not in headers

    # gets internal token for GET request to users with external ID
    response = await client.get(
        f"{USERS_PATH}/someone@aai.org", headers={"Authorization": auth}
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization
    assert "X-Authorization" not in headers

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"name", "email", "ext_id", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["name"] == "John Doe"
    assert claims["email"] == "john@home.org"
    assert claims["ext_id"] == "john@aai.org"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]

    # gets internal token for POST request to users
    response = await client.post(USERS_PATH, headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization
    assert "X-Authorization" not in headers

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"name", "email", "ext_id", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["name"] == "John Doe"
    assert claims["email"] == "john@home.org"
    assert claims["ext_id"] == "john@aai.org"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]


@mark.asyncio
async def test_token_exchange_for_known_user(
    client: AsyncTestClient, httpx_mock: HTTPXMock
):
    """Test the token exchange for authenticated and registered users."""
    user_dao: UserDao = cast(UserDao, DummyUserDao())
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao
    claim_dao: ClaimDao = cast(ClaimDao, DummyClaimDao())
    main.app.dependency_overrides[get_claim_dao] = lambda: claim_dao
    user = user_dao.user  # pyright: ignore

    assert user.status is UserStatus.ACTIVE
    assert user.status_change is None

    # Check that we get an internal token for the user

    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    auth = f"Bearer {create_access_token()}"
    response = await client.get("/some/path", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization
    assert "X-Authorization" not in headers

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"id", "name", "email", "status", "title", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["id"] == user.id
    assert claims["name"] == user.name
    assert claims["email"] == user.email
    assert claims["status"] == "active"
    assert claims["title"] is None
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]

    # Check that the user becomes invalid when the name has changed

    httpx_mock.add_response(
        url=RE_USER_INFO_URL, json={**USER_INFO, "name": "John Foo"}
    )

    auth = f"Bearer {create_access_token()}"
    response = await client.get("/some/path", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization
    assert "X-Authorization" not in headers

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"id", "name", "email", "status", "title", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["id"] == user.id
    assert claims["name"] == "John Foo"  # changed name in internal token
    assert claims["email"] == user.email
    assert claims["status"] == "invalid"  # because there is a name mismatch
    assert claims["title"] is None
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]

    # Check that the user becomes invalid when the mail has changed

    httpx_mock.add_response(
        url=RE_USER_INFO_URL, json={**USER_INFO, "email": "john@foo.org"}
    )

    auth = f"Bearer {create_access_token()}"
    response = await client.get("/some/path", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization
    assert "X-Authorization" not in headers

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"id", "name", "email", "status", "title", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["id"] == user.id
    assert claims["name"] == user.name
    assert claims["email"] == "john@foo.org"  # changed mail in internal token
    assert claims["status"] == "invalid"  # because there is a name mismatch
    assert claims["title"] is None
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]

    # Check that the user was not changed in the database
    assert user.name == "John Doe"
    assert user.email == "john@home.org"
    assert user.status is UserStatus.ACTIVE
    assert user.status_change is None


@mark.asyncio
async def test_token_exchange_with_x_token(
    client: AsyncTestClient, httpx_mock: HTTPXMock
):
    """Test that the external access token can be passed in separate header."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao(ext_id="not.john@aai.org")
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao

    auth = f"Bearer {create_access_token()}"

    # send access token to some path in X-Authorization header
    response = await client.get("/some/path", headers={"X-Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    assert headers.get("Authorization") == ""
    assert "X-Authorization" not in headers

    # send access token in POST request to users to get the internal token
    response = await client.post(USERS_PATH, headers={"X-Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {}

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization
    assert "X-Authorization" not in headers

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"name", "email", "ext_id", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["name"] == "John Doe"
    assert claims["email"] == "john@home.org"
    assert claims["ext_id"] == "john@aai.org"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]


@mark.asyncio
async def test_token_exchange_for_known_data_steward(
    client: AsyncTestClient, httpx_mock: HTTPXMock
):
    """Test the token exchange for an authenticated data steward."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    # add a dummy user who is a data steward
    user_dao: UserDao = cast(UserDao, DummyUserDao(id_="james@ghga.de", title="Dr."))
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao
    claim_dao: ClaimDao = cast(ClaimDao, DummyClaimDao())
    main.app.dependency_overrides[get_claim_dao] = lambda: claim_dao
    user = user_dao.user  # pyright: ignore

    auth = f"Bearer {create_access_token()}"
    response = await client.get("/some/path", headers={"Authorization": auth})
    assert response.status_code == status.HTTP_200_OK

    headers = response.headers
    authorization = headers.get("Authorization")
    assert authorization

    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"id", "name", "email", "status", "title", "exp", "iat", "role"}

    assert set(claims) == expected_claims
    assert claims["id"] == user.id
    assert claims["name"] == user.name
    assert claims["email"] == user.email
    assert claims["title"] == "Dr."
    assert claims["status"] == "active"

    # check that the data steward role appears in the token
    assert claims["role"] == "data_steward"


@mark.asyncio
async def test_post_user_without_session(client: AsyncTestClient):
    """Test authentication for user registration without a session."""
    response = await client.post("/users")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Not logged in"}


@mark.asyncio
async def test_post_user_with_session_and_invalid_csrf(
    client_with_session: ClientWithSession,
):
    """Test user registration with session and invalid CSRF token."""
    client, session = client_with_session[:2]
    session.csrf_token = "invalid"
    response = await client.post("/users", headers=headers_for_session(session))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid or missing CSRF token"}


@mark.asyncio
async def test_post_user_with_session(client: AsyncTestClient, httpx_mock: HTTPXMock):
    """Test user registration with session and valid CSRF token."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao(ext_id="not.john@ghga.de")
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao

    session = await query_new_session(client)

    response = await client.post("/users", headers=headers_for_session(session))

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    authorization = response.headers["Authorization"]
    assert authorization

    internal_token = get_bearer_token(authorization)
    assert internal_token

    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"id", "name", "email", "title", "exp", "iat", "role"}

    assert set(claims) == expected_claims
    assert claims["id"] == "john@aai.org"
    assert claims["name"] == "John Doe"
    assert claims["email"] == "john@home.org"
    assert claims["title"] is None
    assert claims["role"] is None

    iat = claims["iat"]
    assert isinstance(iat, int)
    assert 0 <= now_as_utc().timestamp() - iat < 5
    exp = claims["exp"]
    assert isinstance(exp, int)
    assert 0 <= exp - iat - 3600 < 2
