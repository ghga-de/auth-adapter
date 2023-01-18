# Copyright 2021 - 2023 Universität Tübingen, DKFZ and EMBL
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

"""DTOs for the user management service

Note: we currently use the DTOs also as the core entities.
"""

from enum import Enum
from typing import Optional

from ghga_service_chassis_lib.utils import DateTimeUTC
from pydantic import BaseModel, EmailStr, Field

__all__ = ["User", "UserData", "UserStatus", "StatusChange"]


class UserStatus(str, Enum):
    """User status enum"""

    REGISTERED = "registered"
    ACTIVATED = "activated"
    INACTIVATED = "inactivated"
    DELETED = "deleted"


class AcademicTitle(str, Enum):
    """Academic title"""

    DR = "Dr."
    PROF = "Prof."


class BaseDto(BaseModel):
    """Base model preconfigured for use as Dto."""

    class Config:  # pylint: disable=missing-class-docstring
        extra = "forbid"
        frozen = True


class StatusChange(BaseDto):
    """Details of a status change"""

    previous: UserStatus = Field(default=None, title="Previous user status")
    by: Optional[str] = Field(
        default=None,
        title="Status changed by",
        description="ID of the user who changed the status",
    )
    context: str = Field(default=None, title="Status change context")
    change_date: DateTimeUTC = Field(default=None, title="Date of last change")


class UserCreatableData(BaseDto):
    """User data"""

    ls_id: EmailStr = Field(
        default=...,
        title="LS ID",
        description="Life Science ID",
        example="user@lifescience-ri.eu",
    )
    name: str = Field(
        default=...,
        title="Name",
        description="Full name of the user",
        example="Rosalind Franklin",
    )
    title: Optional[AcademicTitle] = Field(
        default=None, title="Academic title", description="Academic title of the user"
    )
    email: EmailStr = Field(
        default=...,
        title="E-Mail",
        description="Preferred e-mail address of the user",
        example="user@home.org",
    )


class UserModifiableData(BaseDto):
    """User data that can be modified"""

    status: Optional[UserStatus] = Field(
        None, title="Status", description="Registration status of the user"
    )
    title: Optional[AcademicTitle] = Field(
        None, title="Academic title", description="Academic title of the user"
    )


class UserAutomaticData(BaseModel):
    """User data that is automatically created except the ID"""

    registration_date: DateTimeUTC = Field(default=..., title="Registration date")

    status_change: Optional[StatusChange] = None

    submissions: list[str] = Field(
        default=[],
        title="Submissions",
        description="List of IDs of all submissions created by the user",
    )
    access_requests: list[str] = Field(
        default=[],
        title="Access requests",
        description="List of IDs of all data access requests created by the user",
    )


class UserData(UserCreatableData, UserAutomaticData):
    """User data model without the ID"""

    status: UserStatus = Field(
        default=..., title="Status", description="Registration status of the user"
    )


class User(UserData):
    """Complete user model with ID"""

    id: str = Field(  # actually UUID
        default=..., title="ID", description="Internally used ID"
    )
