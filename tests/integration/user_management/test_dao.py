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

from datetime import datetime

from hexkit.providers.mongodb.testutils import (  # noqa: F401; pylint: disable=unused-import
    mongodb_fixture,
)
from pytest import mark

from auth_service.user_management.api.deps import (
    get_config,
    get_user_dao_factory,
    get_user_dao_factory_config,
)
from auth_service.user_management.models.dto import (
    ID,
    AcademicTitleEnum,
    User,
    UserData,
    UserStatusEnum,
)


@mark.asyncio
async def test_user_creation(mongodb_fixture):  # noqa: F811
    """Test creating a new user"""

    config = get_config()
    user_dao_factory_config = get_user_dao_factory_config(config=config)
    user_dao_factory = get_user_dao_factory(
        config=user_dao_factory_config, dao_factory=mongodb_fixture.dao_factory
    )
    user_dao = await user_dao_factory.get_user_dao()

    user_data = UserData(
        ls_id="max@ls.org",
        status=UserStatusEnum.ACTIVATED,
        name="Max Headroom",
        title=AcademicTitleEnum.DR,
        email="max@example.org",
        research_topics="genes",
        registration_reasons="for testing",
        registration_date=datetime(2022, 9, 1, 12, 0),
    )
    user = await user_dao.insert(user_data)
    assert user and isinstance(user, User)
    assert user.ls_id == user_data.ls_id
    assert user.status == user_data.status
    assert user.name == user_data.name
    assert user.title == user_data.title
    assert user.email == user_data.email
    assert user.research_topics == user_data.research_topics
    assert user.registration_reason == user_data.registration_reason
    assert user.registration_date == user_data.registration_date
    assert isinstance(user.id, ID)
    id_ = user.id.__root__
    assert id_ and isinstance(id_, str)
    assert len(id_) == 36 and id_.count("-") == 4  # UUID4
