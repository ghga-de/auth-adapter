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

"""Manage request and response headers"""

import json
from typing import Callable, Optional, Union

from ..core.session_store import Session

__all__ = ["get_bearer_token", "session_to_header"]


def get_bearer_token(*header_values: Optional[str]) -> Optional[str]:
    """Extract the bearer token from the authorization header.

    Multiple possible authorization header values can be passed,
    in case one of them is used for Basic authentication.

    Return None if no bearer token was found in one of the header values.
    """
    for header_value in header_values:
        if header_value and header_value.startswith("Bearer "):
            return header_value.removeprefix("Bearer ")
    return None


def session_to_header(
    session: Session, expires: Optional[Callable[[Session], int]]
) -> str:
    """Serialize a session to a response header value to be used by the frontend."""
    session_dict: dict[str, Union[str, int]] = {
        "userId": session.user_id,
        "name": session.user_name,
        "email": session.user_email,
        "state": session.state.value,
        "csrf": session.csrf_token,
    }
    if session.user_title:
        session_dict["title"] = session.user_title
    if expires:
        session_dict["expires"] = expires(session)
    return json.dumps(session_dict, ensure_ascii=False, separators=(",", ":"))
