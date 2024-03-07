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

"""IVA model classes used as DTOs and core entities.

An IVA is an "indendent verification address" used to verify a user's identity.
"""

from enum import Enum
from typing import Optional

from ghga_service_commons.utils.utc_dates import UTCDatetime
from pydantic import ConfigDict, Field

from . import BaseDto

__all__ = ["IvaType", "IvaState", "IvaData", "IvaFullData", "Iva"]


class IvaType(str, Enum):
    """The type of IVA"""

    PHONE = "Phone"
    FAX = "Fax"
    POSTAL_ADDRESS = "PostalAddress"
    IN_PERSON = "InPerson"


class IvaState(str, Enum):
    """The state of an IVA"""

    UNVERIFIED = "Unverified"
    CODE_REQUESTED = "CodeRequested"
    CODE_CREATED = "CodeCreated"
    CODE_TRANSMITTED = "CodeTransmitted"
    CODE_VERIFIED = "CodeVerified"


class IvaBasicData(BaseDto):
    """Basic IVA data"""

    user_id: str = Field(default=..., description="Internal user ID")
    type: IvaType = Field(default=..., description="The type of the IVA")
    value: str = Field(default=..., description="The actual address")
    state: IvaState = Field(
        default=IvaState.UNVERIFIED, description="The state of the IVA"
    )


class IvaInternalData(BaseDto):
    """Internal data of an IVA (not exposed via the API)"""

    verification_code_hash: Optional[str] = Field(
        default=None, description="Hash of the verification code for the IVA"
    )
    verification_attempts: int = Field(
        default=0,
        description="Number of failed verification attempts for the verification code",
    )


class IvaAutomaticData(BaseDto):
    """Data that is automatically added to an IVA"""

    created: UTCDatetime = Field(
        default=..., description="The date and time when the IVA was created"
    )
    changed: UTCDatetime = Field(
        default=..., description="The date and time when the IVA was last changed"
    )


class IvaData(IvaBasicData, IvaAutomaticData):
    """IVA data model with all external data including ID"""

    # this is the model that is exposed via the API
    model_config = ConfigDict(
        title="IVA",
        json_schema_extra={
            "title": "IVA",
            "description": "Independent Verification Address (IVA)",
        },
    )

    id: str = Field(default=..., description="Internal IVA ID")  # actually UUID


class IvaFullData(IvaBasicData, IvaInternalData, IvaAutomaticData):
    """IVA data model including all internal data without ID"""


class Iva(IvaFullData):
    """IVA data model including internal data and the ID"""

    id: str = Field(default=..., description="Internal IVA ID")  # actually UUID
