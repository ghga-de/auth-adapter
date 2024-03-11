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

"""Implementation of the core user registry."""

import logging
from typing import Any, Optional, Union

from ghga_service_commons.utils.utc_dates import now_as_utc
from hexkit.protocols.dao import (
    NoHitsFoundError,
    ResourceNotFoundError,
)
from pydantic import Field
from pydantic_settings import BaseSettings

from ..models.ivas import Iva, IvaBasicData, IvaData, IvaFullData, IvaState
from ..models.users import (
    StatusChange,
    User,
    UserBasicData,
    UserData,
    UserModifiableData,
    UserRegisteredData,
    UserStatus,
)
from ..ports.registry import UserRegistryPort
from ..translators.dao import IvaDao, UserDao
from .verification_codes import generate_code, hash_code, validate_code

log = logging.getLogger(__name__)

INITIAL_USER_STATUS = UserStatus.ACTIVE


class UserRegistryConfig(BaseSettings):
    """Configuration for the user registry."""

    max_iva_verification_attempts: int = Field(
        default=10, description="Maximum number of verification attempts for an IVA"
    )


class UserRegistry(UserRegistryPort):
    """Registry for users including their IVAs."""

    def __init__(
        self, *, config: UserRegistryConfig, user_dao: UserDao, iva_dao: IvaDao
    ):
        """Initialize the user registry."""
        self.max_iva_verification_attempts = config.max_iva_verification_attempts
        self.user_dao = user_dao
        self.iva_dao = iva_dao

    @staticmethod
    def is_internal_user_id(id_: str) -> bool:
        """Check if the passed ID is an internal user id."""
        if not id_ or not isinstance(id_, str):
            return False
        return len(id_) == 36 and id_.count("-") == 4 and "@" not in id_

    @staticmethod
    def is_external_user_id(id_: str) -> bool:
        """Check if the passed ID is an external user id."""
        if not id_ or not isinstance(id_, str):
            return False
        return len(id_) > 8 and id_.count("@") == 1

    async def create_user(
        self,
        user_data: UserRegisteredData,
    ) -> User:
        """Create a user with the given registration data.

        May raise a UserAlreadyExistsError or a UserCreationError.
        """
        ext_id = user_data.ext_id
        try:
            if not self.is_external_user_id(ext_id):
                raise ValueError(f"Invalid user ID: {ext_id}")
            user = await self.user_dao.find_one(mapping={"ext_id": ext_id})
        except NoHitsFoundError:
            pass
        except Exception as error:
            log.error("Could not insert user: %s", error)
            raise self.UserCreationError(ext_id=ext_id) from error
        else:
            raise self.UserAlreadyExistsError(ext_id=ext_id)
        full_user_data = UserData(
            **user_data.model_dump(),
            status=INITIAL_USER_STATUS,
            registration_date=now_as_utc(),
        )
        try:
            user = await self.user_dao.insert(full_user_data)
        except Exception as error:
            log.error("Could not insert user: %s", error)
            raise self.UserCreationError(ext_id=ext_id) from error
        return user

    async def get_user(self, user_id: str) -> User:
        """Get user data.

        May raise a UserDoesNotExistError or a UserRetrievalError.
        """
        try:
            if not self.is_internal_user_id(user_id):
                raise ResourceNotFoundError(id_=user_id)
            user = await self.user_dao.get_by_id(user_id)
        except ResourceNotFoundError as error:
            raise self.UserDoesNotExistError(user_id=user_id) from error
        except Exception as error:
            log.error("Could not request user: %s", error)
            raise self.UserRetrievalError(user_id=user_id) from error
        return user

    async def update_user(
        self,
        user_id: str,
        user_data: Union[UserBasicData, UserModifiableData],
        *,
        changed_by: Optional[str] = None,
        context: Optional[str] = None,
    ) -> None:
        """Update user data.

        Status change is allowed and recorded with the specified context.

        May raise UserDoesNotExistError or a UserUpdateError.
        """
        update_data = user_data.model_dump(exclude_unset=True)
        try:
            user = await self.get_user(user_id)
        except self.UserRetrievalError as error:
            raise self.UserUpdateError(user_id=user_id) from error
        if "status" in update_data and user.status != update_data["status"]:
            update_data["status_change"] = StatusChange(
                previous=user.status,
                by=(changed_by or "").strip() or None,
                context=(context or "").strip() or None,
                change_date=now_as_utc(),
            )
        try:
            user = user.model_copy(update=update_data)
            await self.user_dao.update(user)
        except ResourceNotFoundError as error:
            log.warning("User not found: %s", error)
            raise self.UserDoesNotExistError(user_id=user_id) from error
        except Exception as error:
            log.error("Could not update user: %s", error)
            raise self.UserUpdateError(user_id=user_id) from error

    async def delete_user(self, user_id: str) -> None:
        """Delete a user.

        This also deletes all IVAs belonging to the user.

        May raise a UserDoesNotExistError or a UserDeletionError.
        """
        try:
            if not self.is_internal_user_id(user_id):
                raise ResourceNotFoundError(id_=user_id)
            await self.user_dao.delete(id_=user_id)
        except ResourceNotFoundError as error:
            raise self.UserDoesNotExistError(user_id=user_id) from error
        except Exception as error:
            log.error("Could not delete user: %s", error)
            raise self.UserDeletionError(user_id=user_id) from error
        try:
            try:
                async for iva in self.iva_dao.find_all(mapping={"user_id": user_id}):
                    await self.iva_dao.delete(id_=iva.id)
            except ResourceNotFoundError:
                pass
        except Exception as error:
            log.error("Could not delete IVAs of user: %s", error)
            raise self.UserDeletionError(user_id=user_id) from error

    async def create_iva(self, user_id: str, data: IvaBasicData) -> str:
        """Create an IVA for the given user with the given basic data.

        Returns the internal ID of the newly createdIVA.

        May raise a UserDoesNotExistError or an IvaCreationError.
        """
        try:
            await self.get_user(user_id)
        except self.UserRetrievalError as error:
            raise self.IvaCreationError(user_id=user_id) from error
        created = changed = now_as_utc()
        iva_data = IvaFullData(
            **data.model_dump(), user_id=user_id, created=created, changed=changed
        )
        try:
            iva = await self.iva_dao.insert(iva_data)
        except Exception as error:
            log.error("Could not create IVA: %s", error)
            raise self.IvaCreationError(user_id=user_id) from error
        return iva.id

    async def get_iva(self, iva_id: str, *, user_id: Optional[str] = None) -> Iva:
        """Get the IVA with the given ID.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError,
        orr an IvaRetrievalError.
        """
        try:
            iva = await self.iva_dao.get_by_id(iva_id)
        except ResourceNotFoundError as error:
            raise self.IvaDoesNotExistError(iva_id=iva_id) from error
        if user_id and iva.user_id != user_id:
            raise self.IvaDoesNotExistError(iva_id=iva_id, user_id=user_id)
        return iva

    async def get_ivas(self, user_id: str) -> list[IvaData]:
        """Get all IVAs of a user.

        The internal data of the IVAs is not included in the result.

        May raise an IvaRetrievalError.
        """
        external_fields = IvaData.model_fields
        try:
            return [
                IvaData(**iva.model_dump(include=external_fields))
                async for iva in self.iva_dao.find_all(mapping={"user_id": user_id})
            ]
        except Exception as error:
            log.error("Could not retrieve IVAs: %s", error)
            raise self.IvaRetrievalError(user_id=user_id) from error

    async def update_iva(self, iva: Iva, **update: Any) -> None:
        """Update the IVA with the given data.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError
        or an IvaModificationError.
        """
        if "changed" not in update:
            update["changed"] = now_as_utc()
        iva = iva.model_copy(update=update)
        try:
            await self.iva_dao.update(iva)
        except ResourceNotFoundError as error:
            log.warning("IVA not found: %s", error)
            raise self.IvaDoesNotExistError(iva_id=iva.id) from error
        except Exception as error:
            log.error("Could not update IVA: %s", error)
            raise self.IvaModificationError(iva_id=iva.id) from error

    async def delete_iva(self, iva_id: str, *, user_id: Optional[str] = None) -> None:
        """Delete the IVA with the ID.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError
        or an IvaDeletionError.

        If a user ID is specified, and the IVA does not belong to the user,
        then an IvaDoesNotExistError is raised.
        """
        if user_id:
            await self.get_iva(iva_id, user_id=user_id)
        try:
            await self.iva_dao.delete(id_=iva_id)
        except ResourceNotFoundError as error:
            raise self.IvaDoesNotExistError(iva_id=iva_id) from error
        except Exception as error:
            log.error("Could not delete IVA: %s", error)
            raise self.IvaDeletionError(iva_id=iva_id) from error

    async def unverify_iva(self, iva_id: str):
        """Reset an IVA as being unverified.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError,
        an IvaRetrievalError or an IvaModificationError.
        """
        iva = await self.get_iva(iva_id)
        await self.update_iva(
            iva,
            state=IvaState.UNVERIFIED,
            verification_code_hash=None,
            verification_attempts=0,
        )
        # TODO: should also send a notification to the user

    async def request_iva_verification_code(
        self, iva_id: str, *, user_id: Optional[str] = None
    ):
        """Request a verification code for the IVA with the given ID.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError,
        an IvaRetrievalError, an IvaUnexpectedStateError or an IvaModificationError.

        If a user ID is specified, and the IVA does not belong to the user,
        then an IvaDoesNotExistError is raised.
        """
        iva = await self.get_iva(iva_id, user_id=user_id)
        if iva.state is not IvaState.UNVERIFIED:
            raise self.IvaUnexpectedStateError(iva_id=iva_id, state=iva.state)
        await self.update_iva(iva, state=IvaState.CODE_REQUESTED)
        # TODO: should also send a notification to the user and a data steward

    async def create_iva_verification_code(self, iva_id: str) -> str:
        """Create a verification code for the IVA with the given ID.

        The code is returned as a string and its hash is stored in the database.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError,
        an IvaRetrievalError, an IvaUnexpectedStateError or an IvaModificationError.
        """
        iva = await self.get_iva(iva_id)
        if iva.state not in (IvaState.CODE_REQUESTED, IvaState.CODE_CREATED):
            raise self.IvaUnexpectedStateError(iva_id=iva_id, state=iva.state)
        code = generate_code()
        await self.update_iva(
            iva,
            state=IvaState.CODE_CREATED,
            verification_code_hash=hash_code(code),
            verification_attempts=0,
        )
        return code

    async def confirm_iva_code_transmission(self, iva_id: str) -> None:
        """Confirm the transmission of the verification code for the given IVA.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError,
        an IvaRetrievalError, an IvaUnexpectedStateError or an IvaModificationError.
        """
        iva = await self.get_iva(iva_id)
        if iva.state is not IvaState.CODE_CREATED:
            raise self.IvaUnexpectedStateError(iva_id=iva_id, state=iva.state)
        await self.update_iva(
            iva,
            state=IvaState.CODE_TRANSMITTED,
        )
        # TODO: should also send a notification to the user

    async def validate_iva_verification_code(
        self, iva_id: str, code: str, *, user_id: Optional[str] = None
    ) -> bool:
        """Validate a verification code for the given IVA.

        Checks whether the given verification code matches the stored hash.

        May raise a UserRegistryIvaError, which can be an IvaDoesNotExistError,
        an IvaIvaRetrievalError, an IvaUnexpectedStateError,
        an IvaTooManyVerificationAttemptsError or an IvaModificationError.

        If a user ID is specified, and the IVA does not belong to the user,
        then an IvaDoesNotExistError is raised.
        """
        iva = await self.get_iva(iva_id, user_id=user_id)
        if (
            iva.state not in (IvaState.CODE_CREATED, IvaState.CODE_TRANSMITTED)
            or not iva.verification_code_hash
        ):
            raise self.IvaUnexpectedStateError(iva_id=iva_id, state=iva.state)
        too_many = iva.verification_attempts >= self.max_iva_verification_attempts
        validated = not too_many and validate_code(code, iva.verification_code_hash)
        change: dict[str, Any] = {}
        if too_many:
            change.update(state=IvaState.UNVERIFIED)
        elif validated:
            change.update(state=IvaState.VERIFIED)
        if too_many or validated:
            change.update(verification_code_hash=None, verification_attempts=0)
        else:
            change.update(verification_attempts=iva.verification_attempts + 1)
        await self.update_iva(iva, **change)
        if too_many:
            raise self.IvaTooManyVerificationAttemptsError(iva_id=iva_id)
        # TODO: should also send a notification to the data steward
        return validated
