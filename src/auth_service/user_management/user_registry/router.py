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

"""Routes for managing users and IVAs"""

from typing import Annotated

from fastapi import APIRouter, Path, Response
from fastapi.exceptions import HTTPException

from ..auth import (
    StewardAuthContext,
    UserAuthContext,
    is_steward,
)
from .deps import Depends, get_user_registry
from .models.ivas import IvaData
from .models.users import (
    User,
    UserBasicData,
    UserModifiableData,
    UserRegisteredData,
    UserStatus,
)
from .ports.registry import UserRegistryPort

__all__ = ["router"]

router = APIRouter()

INITIAL_USER_STATUS = UserStatus.ACTIVE


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
        403: {"description": "Not authorized to register user."},
        409: {"description": "User was already registered."},
        422: {"description": "Validation error in submitted user data."},
    },
    status_code=201,
)
async def post_user(
    user_data: UserRegisteredData,
    user_registry: Annotated[UserRegistryPort, Depends(get_user_registry)],
    auth_context: UserAuthContext,
) -> User:
    """Register a user."""
    ext_id = user_data.ext_id
    # note that the auth context contains the external ID for this endpoint (only)
    if ext_id != auth_context.id:  # users can only register themselves
        raise HTTPException(status_code=403, detail="Not authorized to register user.")
    if not (
        user_registry.is_external_user_id(ext_id)
        and user_data.name == auth_context.name  # specified name must match token
        and user_data.email == auth_context.email  # specified email must match token
    ):
        raise HTTPException(status_code=422, detail="User cannot be registered.")
    try:
        return await user_registry.create_user(user_data)
    except user_registry.UserAlreadyExistsError as error:
        raise HTTPException(
            status_code=409, detail="User was already registered."
        ) from error
    except user_registry.UserCreationError as error:
        raise HTTPException(
            status_code=500, detail="User cannot be registered."
        ) from error


@router.put(
    "/users/{id}",
    operation_id="put_user",
    tags=["users"],
    summary="Update a user",
    description="Endpoint used to update a registered user"
    " when their name or email used by LS Login have changed."
    " May only be performed by the users themselves."
    " Data delivered by the OIDC provider may not be altered.",
    responses={
        204: {"description": "User was successfully updated."},
        403: {"description": "Not authorized to update user."},
        404: {"description": "User does not exist."},
        422: {"description": "Validation error in submitted user data."},
    },
    status_code=204,
)
async def put_user(
    user_data: UserBasicData,
    id_: Annotated[
        str,
        Path(
            ...,
            alias="id",
            description="Internal ID",
        ),
    ],
    user_registry: Annotated[UserRegistryPort, Depends(get_user_registry)],
    auth_context: UserAuthContext,
) -> Response:
    """Update a user."""
    if id_ != auth_context.id:  # users can only update themselves
        raise HTTPException(status_code=403, detail="Not authorized to update user.")
    if not (
        user_registry.is_internal_user_id(id_)
        and user_data.name == auth_context.name  # specified name must match token
        and user_data.email == auth_context.email  # specified email must match token
    ):
        raise HTTPException(status_code=422, detail="User cannot be updated.")
    try:
        await user_registry.update_user(id_, user_data)
    except user_registry.UserDoesNotExistError as error:
        raise HTTPException(status_code=404, detail="User does not exist.") from error
    except user_registry.UserUpdateError as error:
        raise HTTPException(
            status_code=500, detail="User cannot be updated."
        ) from error
    return Response(status_code=204)


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
        403: {"description": "Not authorized to request user."},
        404: {"description": "The user was not found."},
        422: {"description": "Validation error in submitted user identification."},
    },
    status_code=200,
)
async def get_user(
    id_: Annotated[
        str,
        Path(
            ...,
            alias="id",
            description="Internal User ID",
        ),
    ],
    user_registry: Annotated[UserRegistryPort, Depends(get_user_registry)],
    auth_context: UserAuthContext,
) -> User:
    """Get user data."""
    # only data stewards can request other user accounts
    if not (is_steward(auth_context) or id_ == auth_context.id):
        raise HTTPException(status_code=403, detail="Not authorized to request user.")
    try:
        user = await user_registry.get_user(id_)
    except user_registry.UserDoesNotExistError as error:
        raise HTTPException(
            status_code=404, detail="The user was not found."
        ) from error
    except user_registry.UserRetrievalError as error:
        raise HTTPException(
            status_code=500, detail="The user cannot be requested."
        ) from error
    if not is_steward(auth_context) and user.status_change is not None:
        # only data stewards should be able to see the status change information
        user = user.model_copy(update={"status_change": None})
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
        403: {"description": "Not authorized to make this modification."},
        404: {"description": "The user was not found."},
        422: {"description": "Validation error in submitted user data."},
    },
    status_code=201,
)
async def patch_user(
    user_data: UserModifiableData,
    id_: Annotated[
        str,
        Path(
            ...,
            alias="id",
            description="Internal ID",
        ),
    ],
    user_registry: Annotated[UserRegistryPort, Depends(get_user_registry)],
    auth_context: UserAuthContext,
) -> Response:
    """Modify user data."""
    # Everybody is allowed to modify their own data except the status,
    # but only data stewards are allowed to modify other accounts
    allowed = (
        "status" not in user_data.model_fields_set
        if id_ == auth_context.id
        else is_steward(auth_context)
    )
    if not allowed:
        raise HTTPException(
            status_code=403, detail="Not authorized to make this modification."
        )
    try:
        await user_registry.update_user(
            id_,
            user_data,
            changed_by=auth_context.id,
            context="manual change",
        )
    except user_registry.UserDoesNotExistError as error:
        raise HTTPException(
            status_code=404, detail="The user was not found."
        ) from error
    except user_registry.UserRetrievalError as error:
        raise HTTPException(
            status_code=500, detail="The user cannot be modified."
        ) from error
    return Response(status_code=204)


@router.delete(
    "/users/{id}",
    operation_id="delete_user",
    tags=["users"],
    summary="Delete user",
    description="Endpoint used to delete a user."
    " Can only be performed by a data steward.",
    responses={
        204: {"description": "User data was successfully deleted."},
        403: {"description": "Not authorized to delete this user."},
        404: {"description": "The user was not found."},
        422: {"description": "Validation error in submitted user identification."},
    },
    status_code=201,
)
async def delete_user(
    id_: Annotated[
        str,
        Path(
            ...,
            alias="id",
            description="Internal ID",
        ),
    ],
    user_registry: Annotated[UserRegistryPort, Depends(get_user_registry)],
    auth_context: StewardAuthContext,
) -> Response:
    """Delete user."""
    if id_ == auth_context.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this user."
        )
    try:
        await user_registry.delete_user(id_)
    except user_registry.UserDoesNotExistError as error:
        raise HTTPException(
            status_code=404, detail="The user was not found."
        ) from error
    except user_registry.UserRetrievalError as error:
        raise HTTPException(
            status_code=500, detail="The user cannot be deleted."
        ) from error
    return Response(status_code=204)


@router.get(
    "/users/{user_id}/ivas",
    operation_id="get_ivas",
    tags=["users"],
    summary="Get all IVAs of a user",
    description="Endpoint used to get all IVAs for a specified user."
    " Can only be performed by a data steward or the same user.",
    responses={
        200: {
            "model": list[IvaData],
            "description": "User IVAs have been retrieved.",
        },
        401: {"description": "Not authorized to request IVAs."},
        403: {"description": "Not authorized to request these IVAs."},
        422: {"description": "Validation error in submitted user identification."},
    },
    status_code=200,
)
async def get_ivas(
    user_id: Annotated[
        str,
        Path(
            ...,
            alias="user_id",
            description="Internal User ID",
        ),
    ],
    user_registry: Annotated[UserRegistryPort, Depends(get_user_registry)],
    auth_context: UserAuthContext,
) -> list[IvaData]:
    """Get all IVAs of a user."""
    # only data steward can request IVAs of other user accounts
    if not (is_steward(auth_context) or user_id == auth_context.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to request these IVAs."
        )
    try:
        return await user_registry.get_ivas(user_id)
    except user_registry.IvaRetrievalError as error:
        raise HTTPException(status_code=500, detail="Cannot retrieve IVAs.") from error
