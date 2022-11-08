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

"""Unit tests for the utils module."""

from pytest import mark

from auth_service.user_management.claims_repository.utils import user_exists

from ...fixtures.utils import DummyUserDao


@mark.asyncio
async def test_user_exists():
    """Test that existence of users can be checked."""
    user_dao = DummyUserDao(id_="some-internal-id")
    assert await user_exists(None, user_dao) is False
    assert await user_exists("some-internal-id", user_dao) is True
    assert await user_exists("other-internal-id", user_dao) is False
