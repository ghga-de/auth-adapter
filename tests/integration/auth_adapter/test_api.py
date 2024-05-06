# Copyright 2021 - 2024 Universität Tübingen, DKFZ, EMBL, and Universität zu Köln
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
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status
from ghga_service_commons.utils.utc_dates import now_as_utc
from pytest_httpx import HTTPXMock

from auth_service.auth_adapter.api import main
from auth_service.auth_adapter.api.headers import get_bearer_token
from auth_service.auth_adapter.core.session_store import SessionState
from auth_service.auth_adapter.deps import get_user_token_dao
from auth_service.user_management.claims_repository.deps import get_claim_dao
from auth_service.user_management.user_registry.deps import get_user_dao

from ...fixtures.utils import (
    DummyClaimDao,
    DummyUserDao,
    DummyUserTokenDao,
    get_claims_from_token,
    headers_for_session,
)
from .fixtures import (
    AUTH_PATH,
    BareClient,
    ClientWithSession,
    fixture_bare_client,  # noqa: F401
    fixture_bare_client_with_session,  # noqa: F401
    fixture_with_basic_auth,  # noqa: F401
    query_new_session,
)
from .test_totp import get_valid_totp_code

pytestmark = pytest.mark.asyncio()

USER_INFO = {
    "name": "John Doe",
    "email": "john@home.org",
    "sub": "john@aai.org",
}
RE_USER_INFO_URL = re.compile(".*/userinfo$")


@pytest.fixture
def non_mocked_hosts() -> list:
    """Do not mock requests to the test server."""
    return ["testserver"]


def assert_has_authorization_header(response, session):
    """Check that the response contains the expected authorization header."""
    assert response.status_code == status.HTTP_200_OK

    assert not response.text
    headers = response.headers
    assert not headers.get("Cookie")
    assert not headers.get("X-Authorization")
    assert not headers.get("X-CSRF-Token")
    assert not headers.get("X-Session")

    authorization = headers.get("Authorization")
    assert authorization
    internal_token = get_bearer_token(authorization)
    assert internal_token
    claims = get_claims_from_token(internal_token)
    assert isinstance(claims, dict)
    expected_claims = {"id", "name", "email", "title", "role", "exp", "iat"}

    assert set(claims) == expected_claims
    assert claims["id"] == session.user_id
    assert claims["name"] == session.user_name
    assert claims["email"] == session.user_email
    assert claims["title"] == session.user_title
    assert claims["role"] == session.role
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["iat"] <= int(now_as_utc().timestamp()) < claims["exp"]
    assert 0 <= claims["exp"] - claims["iat"] - 3600 < 2


def assert_is_authorization_error(response, message: str):
    """Check that the response is a CSRF error."""
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Authorization" not in response.headers
    assert response.json() == {"detail": message}


async def test_get_from_root(bare_client: BareClient):
    """Test that a simple GET request passes."""
    response = await bare_client.get("/")

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers


async def test_get_from_some_path(bare_client: BareClient):
    """Test that a simple GET request passes."""
    response = await bare_client.get("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers


async def test_get_from_some_path_with_query_parameters(bare_client: BareClient):
    """Test that a simple GET request passes."""
    response = await bare_client.get("/some/path?foo=1&bar=2")

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers


async def test_patch_to_some_path(bare_client: BareClient):
    """Test that a PATCH request to a random path passes."""
    response = await bare_client.patch("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers


async def test_post_to_some_path(bare_client: BareClient):
    """Test that a POST request to a random path passes."""
    response = await bare_client.post("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers


async def test_delete_to_some_path(bare_client: BareClient):
    """Test that a DELETE request to a random path passes."""
    response = await bare_client.delete("/some/path")

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers


async def test_basic_auth(with_basic_auth: str, bare_client: BareClient):
    """Test that the root path can be protected with basic authentication."""
    response = await bare_client.get("/")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == 'Basic realm="GHGA Data Portal"'
    assert response.text == "GHGA Data Portal: Not authenticated"

    auth = b64encode(b"bad:credentials").decode("ASCII")
    auth = f"Basic {auth}"
    response = await bare_client.get("/", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == 'Basic realm="GHGA Data Portal"'
    assert response.text == "GHGA Data Portal: Incorrect username or password"

    auth = b64encode(with_basic_auth.encode("UTF-8")).decode("ASCII")
    auth = f"Basic {auth}"
    response = await bare_client.get("/", headers={"Authorization": auth})

    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert response.headers["Authorization"] == ""


async def test_allowed_paths(with_basic_auth: str, bare_client: BareClient):
    """Test that allowed paths are excluded from authentication."""
    assert with_basic_auth

    response = await bare_client.get(
        "/allowed/read/some/thing", headers={"Authorization": "Bearer foo"}
    )
    # access should be allowed without basic authentication
    assert response.status_code == status.HTTP_200_OK
    assert not response.text

    # and authorization headers should be passed through
    assert response.headers["Authorization"] == "Bearer foo"

    response = await bare_client.head("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await bare_client.options("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await bare_client.post(
        "/allowed/write/some/thing", headers={"Authorization": "Bearer bar"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert response.headers["Authorization"] == "Bearer bar"

    response = await bare_client.patch("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await bare_client.delete("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_200_OK

    response = await bare_client.post("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == "GHGA Data Portal: Not authenticated"

    response = await bare_client.delete("/allowed/read/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = await bare_client.get("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == "GHGA Data Portal: Not authenticated"

    response = await bare_client.options("/allowed/write/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = await bare_client.post("/not-allowed/some/thing")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == "GHGA Data Portal: Not authenticated"


async def test_basic_auth_service_logo(with_basic_auth: str, bare_client: BareClient):
    """Test that fetching the service logo is excluded from authentication."""
    assert with_basic_auth

    response = await bare_client.get("/logo.png")
    assert response.status_code == status.HTTP_200_OK

    response = await bare_client.head("/logo.png")
    assert response.status_code == status.HTTP_200_OK

    response = await bare_client.get("/image.png")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = await bare_client.head("/image.png")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_post_user_without_session(bare_client: BareClient):
    """Test authentication for user registration without a session."""
    response = await bare_client.put(AUTH_PATH + "/users/some-internal-id")
    assert_is_authorization_error(response, "Not logged in")


async def test_post_user_with_session_and_invalid_csrf(
    client_with_session: ClientWithSession,
):
    """Test user registration with session and invalid CSRF token."""
    client, session = client_with_session[:2]
    session.csrf_token = "invalid"
    response = await client.post(
        AUTH_PATH + "/users", headers=headers_for_session(session)
    )
    assert_is_authorization_error(response, "Invalid or missing CSRF token")


async def test_post_user_with_session(bare_client: BareClient, httpx_mock: HTTPXMock):
    """Test user registration with session and valid CSRF token."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao(ext_id="not.john@aai.org")
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao

    session = await query_new_session(bare_client)
    assert not session.user_id

    response = await bare_client.post(
        AUTH_PATH + "/users", headers=headers_for_session(session)
    )

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


async def test_put_user_without_session(bare_client: BareClient):
    """Test authentication for user update without a session."""
    response = await bare_client.put(AUTH_PATH + "/users/some-internal-id")
    assert_is_authorization_error(response, "Not logged in")


async def test_put_user_with_session_and_wrong_user_id(
    client_with_session: ClientWithSession,
):
    """Test user update with session and wrong user ID."""
    client, session = client_with_session[:2]
    response = await client.put(
        AUTH_PATH + "/users/jane@ghga.de", headers=headers_for_session(session)
    )
    assert_is_authorization_error(response, "Not registered")


async def test_put_user_with_session_and_invalid_csrf(
    client_with_session: ClientWithSession,
):
    """Test user update with session and invalid CSRF token."""
    client, session = client_with_session[:2]
    session.csrf_token = "invalid"
    response = await client.put(
        AUTH_PATH + "/users/john@ghga.de", headers=headers_for_session(session)
    )
    assert_is_authorization_error(response, "Invalid or missing CSRF token")


async def test_put_unregistered_user_with_session(
    bare_client: BareClient,
    httpx_mock: HTTPXMock,
):
    """Test updating an unregistered user with session."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao(ext_id="not.john@aai.org")
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao

    session = await query_new_session(bare_client)
    assert not session.user_id

    response = await bare_client.put(
        AUTH_PATH + "/users/john@ghga.de", headers=headers_for_session(session)
    )
    assert_is_authorization_error(response, "Not registered")


async def test_put_registered_user_with_session(
    bare_client: BareClient, httpx_mock: HTTPXMock
):
    """Test updating a registered user with session."""
    httpx_mock.add_response(url=RE_USER_INFO_URL, json=USER_INFO)

    user_dao = DummyUserDao()
    main.app.dependency_overrides[get_user_dao] = lambda: user_dao
    user_token_dao = DummyUserTokenDao()
    main.app.dependency_overrides[get_user_token_dao] = lambda: user_token_dao
    claim_dao = DummyClaimDao()
    main.app.dependency_overrides[get_claim_dao] = lambda: claim_dao

    session = await query_new_session(bare_client)
    assert session.user_id == "john@ghga.de"

    response = await bare_client.put(
        AUTH_PATH + "/users/john@ghga.de", headers=headers_for_session(session)
    )

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
    assert claims["id"] == "john@ghga.de"
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


async def test_random_url_authenticated(client_with_session: ClientWithSession):
    """Test access via internal access token for authenticated users."""
    client, session = client_with_session[:2]
    headers = headers_for_session(session)
    without_csrf = {
        header: value for header, value in headers.items() if "CSRF" not in header
    }

    assert session.state is SessionState.REGISTERED
    # make a query to a random path, with a not fully authenticated session
    response = await client.get("/some/path", headers=headers)
    # this should pass through without yielding an authorization header
    assert response.status_code == status.HTTP_200_OK
    assert "Authorization" not in response.headers
    assert response.headers["X-CSRF-Token"] == ""
    assert response.headers["Cookie"] == ""
    response = await client.get("/some/path", headers=without_csrf)
    assert response.status_code == status.HTTP_200_OK
    assert "Authorization" not in response.headers
    assert "X-CSRF-Token" not in response.headers
    assert response.headers["Cookie"] == ""

    # also try a post request to a random path, with the proper CSRF token
    response = await client.post("/some/path", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert "Authorization" not in response.headers
    assert response.headers["X-CSRF-Token"] == ""
    assert response.headers["Cookie"] == ""
    # however, a post request without a CSRF token should fail
    # even if this is not critical here, since we are not yet fully unauthenticated
    response = await client.post("/some/path", headers=without_csrf)
    assert_is_authorization_error(response, "Invalid or missing CSRF token")

    # create second factor and authenticate with that
    response = await client.post(
        AUTH_PATH + "/totp-token",
        json={"user_id": session.user_id, "force": False},
        headers=headers,
    )
    assert response.status_code == status.HTTP_201_CREATED
    uri = response.json()["uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    response = await client.post(
        AUTH_PATH + "/rpc/verify-totp",
        json={"user_id": session.user_id, "totp": get_valid_totp_code(secret)},
        headers=headers,
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not response.text

    # make a query to a random path, without the session
    response = await client.get("/some/path?foo=1&bar=2")
    assert response.status_code == status.HTTP_200_OK
    assert not response.text
    assert "Authorization" not in response.headers
    # make a query to a random path, including the session
    response = await client.get("/some/path?foo=1&bar=2", headers=without_csrf)
    assert_has_authorization_header(response, session)

    # make a post request to a random path, without the CSRF token
    response = await client.post("/some/path", headers=without_csrf)
    assert_is_authorization_error(response, "Invalid or missing CSRF token")
    # make a post request to a random path, with the CSRF token
    response = await client.post("/some/path", headers=headers)
    assert_has_authorization_header(response, session)

    # make a put request to a random path, without the CSRF token
    response = await client.put("/some/path", headers=without_csrf)
    assert_is_authorization_error(response, "Invalid or missing CSRF token")
    # make a put request to a random path, with the CSRF token
    response = await client.put("/some/path", headers=headers)
    assert_has_authorization_header(response, session)

    # make a delete request to a random path, without the CSRF token
    response = await client.delete("/some/path", headers=without_csrf)
    assert_is_authorization_error(response, "Invalid or missing CSRF token")
    # make a delete request to a random path, with the CSRF token
    response = await client.delete("/some/path", headers=headers)
    assert_has_authorization_header(response, session)
