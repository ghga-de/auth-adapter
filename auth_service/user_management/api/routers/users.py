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
#

"Routes for managing users"

import logging

from fastapi import APIRouter, Path, Response
from fastapi.exceptions import HTTPException
from hexkit.protocols.dao import MultipleHitsFoundError, ResourceNotFoundError

from ...core.utils import is_external_id, is_internal_id
from ...models.dto import User, UserData, UserModifiableData
from ...ports.dao import UserDao
from ..deps import Depends, get_user_dao

__all__ = ["router"]

log = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/users",
    operation_id="post_user",
    tags=["users"],
    summary="Register a user",
    description="Endpoint used to register a new user."
    " May only be performed by the users themselves."
    " Data delivered by the OIDC provider may not be altered.",
    responses={
        201: {"model": User, "description": "User was successfully registered."},
        400: {"description": "User cannot be registered."},
        409: {"description": "User was already registered."},
        422: {"description": "Validation error in submitted user data."},
    },
    status_code=201,
)
async def post_user(
    user_data: UserData, user_dao: UserDao = Depends(get_user_dao)
) -> User:
    """Register a user"""
    ls_id = user_data.ls_id
    user = await user_dao.find_one(mapping={"ls_id": ls_id})
    if user:
        raise HTTPException(status_code=409, detail="User was already registered.")
    try:
        user = await user_dao.insert(user_data)
    except Exception as error:
        log.error("Could not insert user: %s", error)
        raise HTTPException(
            status_code=400, detail="User cannot be registered."
        ) from error
    return user


@router.get(
    "/users/{id}",
    operation_id="get_user",
    tags=["users"],
    summary="Get user data",
    description="Endpoint used to get the user data for a specified user."
    " Can only be performed by a data steward or the same user.",
    responses={
        200: {"model": User, "description": "Requested user has been found."},
        401: {"description": "Not authorized to get user data."},
        404: {"description": "The user was not found."},
        422: {"description": "Validation error in submitted user identification."},
    },
    status_code=200,
)
async def get_user(
    id_: str = Path(
        ...,
        alias="id",
        title="Internal ID or LS ID",
    ),
    user_dao: UserDao = Depends(get_user_dao),
) -> User:
    """Get user data"""
    try:
        if is_external_id(id_):
            user = await user_dao.find_one(mapping={"ls_id": id_})
        elif is_internal_id(id_):
            user = await user_dao.get(id_=id_)
        else:
            user = None
        if not user:
            raise ResourceNotFoundError(id_=id_)
    except (MultipleHitsFoundError, ResourceNotFoundError) as error:
        raise HTTPException(
            status_code=404, detail="The user was not found."
        ) from error
    except Exception as error:
        log.error("Could not request user: %s", error)
        raise HTTPException(
            status_code=500, detail="The user cannot be requested."
        ) from error
    return user


@router.patch(
    "/users/{id}",
    operation_id="patch_user",
    tags=["users"],
    summary="Modify user data",
    description="Endpoint used to modify the user data for a specified user."
    " Can only be performed by a data steward or the same user.",
    responses={
        204: {"description": "User data was successfully saved."},
        404: {"description": "The user was not found."},
        422: {"description": "Validation error in submitted user data."},
    },
    status_code=201,
)
async def patch_user(
    user_data: UserModifiableData,
    id_: str = Path(
        ...,
        alias="id",
        title="Internal ID",
    ),
    user_dao: UserDao = Depends(get_user_dao),
) -> User:
    """Modify user data"""
    try:
        if not is_internal_id(id_):
            raise ResourceNotFoundError(id_=id_)
        user = await user_dao.get(id_=id_)
        update_data = user_data.dict(exclude_unset=True)
        user = user.copy(update=update_data)
        await user_dao.update(user)
    except ResourceNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="The user was not found."
        ) from error
    except Exception as error:
        log.error("Could not modify user: %s", error)
        raise HTTPException(
            status_code=500, detail="The user cannot be modified."
        ) from error

    return Response(status_code=204)
