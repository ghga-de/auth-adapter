# Copyright 2021 - 2022 Universität Tübingen, DKFZ and EMBL
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

from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from ghga_service_chassis_lib.api import configure_app

from ...config import CONFIG, configure_logging
from ...deps import Depends, UserDao, get_user_dao
from .. import DESCRIPTION, TITLE, VERSION
from ..core.auth import exchange_token
from .basic import basic_auth
from .headers import get_bearer_token

configure_logging()

app = FastAPI(title=TITLE, description=DESCRIPTION, version=VERSION)
configure_app(app, config=CONFIG)

# the auth adapter needs to handle all HTTP methods
HANDLE_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]


@app.api_route("/.well-known/{path:path}", methods=["GET"])
async def ext_auth_well_known() -> dict:
    """Unprotected route for the .well-known URLs."""
    return {}


@app.api_route("/{path:path}", methods=HANDLE_METHODS)
async def ext_auth(  # pylint:disable=too-many-arguments
    path: str,
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(default=None),
    x_authorization: Optional[str] = Header(default=None),
    user_dao: UserDao = Depends(get_user_dao),
    _basic_auth: None = basic_auth(app, config=CONFIG),
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
        internal_token = await exchange_token(
            access_token, pass_sub=pass_sub, user_dao=user_dao
        )
        if internal_token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
            )
    else:
        internal_token = None
    # since we cannot delete a header, we set it to an empty string if invalid
    response.headers["Authorization"] = internal_token or ""
    return {}


def path_needs_ext_info(path: str, method: str) -> bool:
    """Check whether the given request path and method need external user info."""
    return (method == "POST" and path == "users") or (
        method == "GET" and path.startswith("users/") and "@" in path
    )
