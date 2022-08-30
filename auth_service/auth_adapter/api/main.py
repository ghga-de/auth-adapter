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
"""

from typing import Optional

from fastapi import FastAPI, Header, Response
from ghga_service_chassis_lib.api import configure_app

from ...config import CONFIG
from ..core.auth import exchange_token
from .basic import basic_auth_injector
from .headers import get_access_token

app = FastAPI()
configure_app(app, config=CONFIG)

# the auth adapter needs to handle all HTTP methods
HANDLE_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]


@app.api_route("/.well-known/{path:path}", methods=["GET"])
async def ext_auth_well_known() -> dict:
    """Unprotected route for the .well-known URLs."""
    return {}


@app.api_route("/{path:path}", methods=HANDLE_METHODS)
async def ext_auth(
    response: Response,
    authorization: Optional[str] = Header(default=None),
    _basic_auth: None = basic_auth_injector(app),
) -> dict:
    """Implements the ExtAuth protocol to authenticate users in the API gateway.

    A valid external access token will be replaced with a corresponding internal token.
    If the access token does not exist or is invalid, no internal token will be placed,
    but the status will still be returned as OK so that all requests can pass.
    """
    access_token = get_access_token(authorization)
    internal_token = exchange_token(access_token)
    if internal_token:
        response.headers[CONFIG.token_name] = internal_token
    del response.headers["authorization"]
    return {}
