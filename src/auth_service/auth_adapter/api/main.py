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

"""
Module containing the main FastAPI router and (optionally) top-level API endpoints.
Additional endpoints might be structured in dedicated modules
(each of them having a sub-router).

Note: If a path_prefix is used for the Emissary AuthService,
then this must be also specified in the config setting api_root_path.
"""

from typing import Annotated, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from ghga_service_commons.api import configure_app
from hexkit.protocols.dao import NoHitsFoundError, ResourceNotFoundError
from pydantic import SecretStr

from auth_service.config import CONFIG
from auth_service.user_management.claims_repository.deps import ClaimDao, get_claim_dao
from auth_service.user_management.user_registry.deps import (
    Depends,
    UserDao,
    get_user_dao,
)
from auth_service.user_management.user_registry.models.dto import User

from .. import DESCRIPTION, TITLE, VERSION
from ..core.auth import (
    TokenValidationError,
    UserInfoError,
    exchange_token,
    get_user_info,
    internal_token_from_session,
)
from ..core.session_store import SessionState
from ..deps import (
    SessionDependency,
    SessionStoreDependency,
    TOTPHandlerDependency,
    UserTokenDao,
    get_user_token_dao,
)
from ..ports.dao import UserToken
from .basic import get_basic_auth_dependency
from .csrf import check_csrf
from .dto import CreateTOTPToken, TOTPTokenResponse, VerifyTOTP
from .headers import get_bearer_token, session_to_header

app = FastAPI(title=TITLE, description=DESCRIPTION, version=VERSION)
configure_app(app, config=CONFIG)

# the auth adapter needs to handle all HTTP methods
READ_METHODS = ["GET", "HEAD", "OPTIONS"]
WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]
ALL_METHODS = READ_METHODS + WRITE_METHODS

API_EXT_PATH = CONFIG.api_ext_path.strip("/")
if API_EXT_PATH:
    API_EXT_PATH += "/"


def add_allowed_route(route: str, write: bool = False):
    """Add a route that shall be passed through."""
    methods = WRITE_METHODS if write else READ_METHODS
    if route.endswith("/*"):
        route = route[:-1] + "{path:path}"
    elif "*" in route:
        route = route.replace("*", "{variable}")

    @app.api_route(route, methods=methods)
    async def allowed_route(
        response: Response, authorization: Annotated[Optional[str], Header()] = None
    ) -> dict:
        """Unprotected route."""
        if authorization:
            response.headers["Authorization"] = authorization
        return {}


def add_allowed_routes():
    """Add all routes that shall be passed through."""
    for route in CONFIG.allow_read_paths:
        add_allowed_route(route, write=False)
    for route in CONFIG.allow_write_paths:
        add_allowed_route(route, write=True)


add_allowed_routes()


@app.post(
    "/rpc/login",
    operation_id="login",
    tags=["users"],
    summary="Create or get user session",
    description="Endpoint used when a user wants to log in.",
    status_code=204,
)
async def login(  # noqa: PLR0913
    session_store: SessionStoreDependency,
    session: SessionDependency,
    user_dao: Annotated[UserDao, Depends(get_user_dao)],
    token_dao: Annotated[UserTokenDao, Depends(get_user_token_dao)],
    authorization: Annotated[Optional[str], Header()] = None,
    x_authorization: Annotated[Optional[str], Header()] = None,
    x_csrf_token: Annotated[Optional[str], Header()] = None,
) -> Response:
    """Create a new or get an existing user session."""
    check_csrf("POST", x_csrf_token, session)
    if session:
        session_created = False
    else:
        access_token = get_bearer_token(authorization, x_authorization)
        try:
            ext_id, user_name, user_email = get_user_info(access_token)
        except UserInfoError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
            ) from error
        session = await session_store.create_session(
            ext_id=ext_id, user_name=user_name, user_email=user_email
        )
        session_created = True
    if session.user_id:
        try:
            user = await user_dao.get_by_id(session.user_id)
        except ResourceNotFoundError:
            user = None  # user has been deleted
    else:
        try:
            user = await user_dao.find_one(mapping={"ext_id": session.ext_id})
        except NoHitsFoundError:
            user = None  # user is not yet registered

    async def has_totp_token(user: User) -> bool:
        try:
            _ = await token_dao.get_by_id(user.id)
        except ResourceNotFoundError:
            return False
        return True

    await session_store.save_session(session, user=user, has_totp_token=has_totp_token)

    response = Response(status_code=204)
    response.headers["X-Session"] = session_to_header(
        session, timeouts=session_store.timeouts
    )
    if session_created:
        response.set_cookie(
            key="session",  # the name of the cookie
            value=session.session_id,
            secure=True,  # only send cookie over HTTPS
            httponly=True,  # don't allow JavaScript to access the cookie
            samesite="lax",  # allow browser to send cookies on top-level navigation
        )
    return response


@app.post(
    "/rpc/logout",
    operation_id="logout",
    tags=["users"],
    summary="End user session",
    description="Endpoint used when a user wants to log out.",
    status_code=204,
)
async def logout(
    session_store: SessionStoreDependency,
    session: SessionDependency,
    x_csrf_token: Annotated[Optional[str], Header()] = None,
) -> Response:
    """End the user session."""
    if session:
        check_csrf("POST", x_csrf_token, session)
        await session_store.delete_session(session.session_id)
    return Response(status_code=204)


@app.post(
    "/users",
    operation_id="post_user",
    tags=["users"],
    summary="Register a user",
    description="Authenticate the endpoint used to register a new user.",
    status_code=200,
)
async def post_user(
    session: SessionDependency,
    x_csrf_token: Annotated[Optional[str], Header()] = None,
) -> Response:
    """Register a user."""
    response = Response(status_code=200)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in"
        )
    check_csrf("POST", x_csrf_token, session)
    internal_token = internal_token_from_session(session)
    authorization = f"Bearer {internal_token}"
    response.headers["Authorization"] = authorization
    return response


@app.post(
    "/totp-token",
    operation_id="create_new_totp_token",
    tags=["totp"],
    summary="Create a new TOTP token",
    description="Endpoint used to create or replace a TOTP token.",
    status_code=201,
)
async def create_new_totp_token(
    creation_info: CreateTOTPToken,
    session_store: SessionStoreDependency,
    session: SessionDependency,
    totp_handler: TOTPHandlerDependency,
    x_csrf_token: Annotated[Optional[str], Header()] = None,
) -> TOTPTokenResponse:
    """Create a new TOTP token or replace an existing one."""
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in"
        )
    if not session.user_id or session.user_id != creation_info.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not registered"
        )
    check_csrf("POST", x_csrf_token, session)
    state = session.state
    if not (
        state in (SessionState.REGISTERED, SessionState.NEW_TOTP_TOKEN)
        or (
            state in (SessionState.HAS_TOTP_TOKEN, SessionState.AUTHENTICATED)
            and creation_info.force
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot create TOTP token at this point",
        )
    session.totp_token = totp_handler.generate_token()
    session.state = SessionState.NEW_TOTP_TOKEN
    await session_store.save_session(session)
    uri = totp_handler.get_provisioning_uri(session.totp_token, name=session.user_name)
    return TOTPTokenResponse(uri=SecretStr(uri))


@app.post(
    "/rpc/verify-totp",
    operation_id="verify_totp",
    tags=["totp"],
    summary="Verify a TOTP code",
    description="Endpoint used to verify a TOTP code.",
    status_code=204,
)
async def verify_totp(  # noqa: PLR0913
    verification_info: VerifyTOTP,
    session_store: SessionStoreDependency,
    session: SessionDependency,
    totp_handler: TOTPHandlerDependency,
    user_dao: Annotated[UserDao, Depends(get_user_dao)],
    token_dao: Annotated[UserTokenDao, Depends(get_user_token_dao)],
    x_csrf_token: Annotated[Optional[str], Header()] = None,
) -> Response:
    """Verify a TOTP token."""
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in"
        )
    if not session.user_id or session.user_id != verification_info.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not registered"
        )
    check_csrf("POST", x_csrf_token, session)
    totp = verification_info.totp
    if session.state == SessionState.NEW_TOTP_TOKEN:
        # get not yet verified TOTP token from the session
        totp_token = session.totp_token
    else:
        # get verified TOTP token from the database
        user = await user_dao.get_by_id(verification_info.user_id)
        user_token = await token_dao.get_by_id(user.id) if user and user.id else None
        totp_token = user_token.totp_token if user_token else None
    if not totp_token or not totp or not totp_handler.verify_code(totp_token, totp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code"
        )
    if session.state == SessionState.NEW_TOTP_TOKEN:
        # TODO: this operation must also delete all IVAs of the user
        # store token in the database
        user_token = UserToken(
            user_id=session.user_id,
            totp_token=totp_token,
        )
        await token_dao.upsert(user_token)
    session.state = SessionState.AUTHENTICATED
    session.totp_token = None  # remove verified TOTP token from the session
    await session_store.save_session(session)
    return Response(status_code=204)


basic_auth_dependency = get_basic_auth_dependency(app, CONFIG)
basic_auth_dependencies = [basic_auth_dependency] if basic_auth_dependency else None


@app.api_route(
    "/{path:path}", methods=ALL_METHODS, dependencies=basic_auth_dependencies
)
async def ext_auth(  # noqa: PLR0913
    path: str,
    request: Request,
    response: Response,
    user_dao: Annotated[UserDao, Depends(get_user_dao)],
    claim_dao: Annotated[ClaimDao, Depends(get_claim_dao)],
    authorization: Annotated[Optional[str], Header()] = None,
    x_authorization: Annotated[Optional[str], Header()] = None,
) -> dict:
    """Implements the ExtAuth protocol to authenticate users in the API gateway.

    A valid external access token will be replaced with a corresponding internal token.
    If the access token does not exist or is invalid, no internal token will be placed,
    but the status will still be returned as OK so that all requests can pass.
    """
    access_token = get_bearer_token(authorization, x_authorization)
    if access_token:
        # check whether the external id is of interest and only pass it on in that case
        pass_sub = path_needs_ext_info(path, request.method)
        try:
            internal_token = await exchange_token(
                access_token, pass_sub=pass_sub, user_dao=user_dao, claim_dao=claim_dao
            )
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
            ) from exc
        except UserInfoError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Error in user info"
            ) from exc
    else:
        internal_token = ""  # nosec
    # since ExtAuth cannot delete a header, we set it to an empty string if invalid
    authorization = f"Bearer {internal_token}" if internal_token else ""
    response.headers["Authorization"] = authorization
    return {}


def path_needs_ext_info(path: str, method: str) -> bool:
    """Check whether the given request path and method need external user info."""
    if API_EXT_PATH:
        if not path.startswith(API_EXT_PATH):
            return False
        path = path[len(API_EXT_PATH) :]
    return (method == "POST" and path == "users") or (
        method == "GET" and path.startswith("users/") and "@" in path
    )
