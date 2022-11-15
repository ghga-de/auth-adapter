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

"""Test Claims models and show some usage examples."""

from datetime import datetime, timezone

from pytest import mark, raises

from auth_service.user_management.claims_repository.models.dto import (
    AuthorityLevel,
    ClaimCreation,
    ClaimMatch,
    Condition,
    Identity,
    MatchClaim,
    MatchType,
    VisaType,
)

UTC = timezone.utc


@mark.parametrize(
    "value",
    ["foo@bar.org", "https://foo.org", [Identity(iss="https://bar.org", sub="baz")]],
)
def test_good_visa_values(value):
    """Test creating an invalid visa value"""
    ClaimCreation(
        user_id="foo-bar",
        visa_type=VisaType.CONTROLLED_ACCESS_GRANTS,
        visa_value=value,
        assertion_date=datetime(2022, 9, 1, 12, 0, tzinfo=UTC),
        valid_from=datetime(2022, 10, 1, 0, 0, tzinfo=UTC),
        valid_until=datetime(2022, 10, 31, 23, 59, tzinfo=UTC),
        source="https://foo-bar.org",
    )


@mark.parametrize(
    "value",
    [
        "not-a-valid-value",
        "foo bar baz",
        "https://foo@bar",
        "bad@email@org",
        "ftp://bad.url.org",
        ["not-an-identity"],
        [dict(iss="foo", sub="bar")],
    ],
)
def test_bad_visa_values(value):
    """Test creating an invalid visa value"""
    with raises(ValueError):
        ClaimCreation(
            user_id="foo-bar",
            visa_type=VisaType.CONTROLLED_ACCESS_GRANTS,
            visa_value=value,
            assertion_date=datetime(2022, 9, 1, 12, 0, tzinfo=UTC),
            valid_from=datetime(2022, 10, 1, 0, 0, tzinfo=UTC),
            valid_until=datetime(2022, 10, 31, 23, 59, tzinfo=UTC),
            source="https://foo-bar.org",
        )


def test_conditions():
    """Test creating a complex condition"""
    ClaimCreation(
        user_id="foo-bar",
        visa_type=VisaType.CONTROLLED_ACCESS_GRANTS,
        visa_value="baz@foo-bar.org",
        assertion_date=datetime(2022, 9, 1, 12, 0, tzinfo=UTC),
        valid_from=datetime(2022, 10, 1, 0, 0, tzinfo=UTC),
        valid_until=datetime(2022, 10, 31, 23, 59, tzinfo=UTC),
        source="https://foo-bar.org",
        sub_source="https://baz.foo-bar.org",
        asserted_by=AuthorityLevel.DAC,
        condition=[
            [
                Condition(
                    type=VisaType.AFFILIATION_AND_ROLE,
                    matches=[
                        ClaimMatch(
                            claim=MatchClaim.VALUE,
                            match_type=MatchType.CONST,
                            match_value="faculty@med.stanford.edu",
                        ),
                        ClaimMatch(
                            claim=MatchClaim.SOURCE,
                            match_type=MatchType.CONST,
                            match_value="https://grid.ac/institutes/grid.240952.8",
                        ),
                        ClaimMatch(
                            claim=MatchClaim.BY,
                            match_type=MatchType.CONST,
                            match_value="so",
                        ),
                    ],
                )
            ],
            [
                Condition(
                    type=VisaType.AFFILIATION_AND_ROLE,
                    matches=[
                        ClaimMatch(
                            claim=MatchClaim.VALUE,
                            match_type=MatchType.CONST,
                            match_value="faculty@med.stanford.edu",
                        ),
                        ClaimMatch(
                            claim=MatchClaim.SOURCE,
                            match_type=MatchType.CONST,
                            match_value="https://grid.ac/institutes/grid.240952.8",
                        ),
                        ClaimMatch(
                            claim=MatchClaim.BY,
                            match_type=MatchType.CONST,
                            match_value="system",
                        ),
                    ],
                )
            ],
        ],
    )


@mark.parametrize(
    "valid_from, valid_until",
    [
        (
            datetime(2022, 10, 1, 0, 0, tzinfo=UTC),
            datetime(2022, 10, 31, 23, 59, tzinfo=UTC),
        ),
        (
            datetime(2001, 12, 31, 23, 59, tzinfo=UTC),
            datetime(2021, 1, 1, 0, 0, tzinfo=UTC),
        ),
        (
            datetime(2020, 6, 15, 12, 59, tzinfo=UTC),
            datetime(2020, 6, 15, 13, 1, tzinfo=UTC),
        ),
        (
            datetime(2022, 2, 28, 13, 1, tzinfo=UTC),
            datetime(2022, 3, 1, 12, 59, tzinfo=UTC),
        ),
        (
            datetime(2021, 12, 31, 23, 59, tzinfo=UTC),
            datetime(2022, 1, 1, 0, 0, tzinfo=UTC),
        ),
    ],
)
def test_validator_period(valid_from, valid_until):
    """Test the validator for valid_from and valid_until"""
    ClaimCreation(
        user_id="foo",
        visa_type=VisaType.RESEARCHER_STATUS,
        visa_value="foo@bar.org",
        assertion_date=datetime(2022, 9, 1, 12, 0, tzinfo=UTC),
        valid_from=valid_from,
        valid_until=valid_until,
        source="https://foo.org",
    )

    with raises(ValueError, match="'valid_until' must be later than 'valid_from'"):
        ClaimCreation(
            user_id="foo",
            visa_type=VisaType.RESEARCHER_STATUS,
            visa_value="foo@bar.org",
            assertion_date=datetime(2022, 9, 1, 12, 0, tzinfo=UTC),
            valid_from=datetime(2022, 10, 1, tzinfo=UTC),
            valid_until=valid_from,
            source="https://foo.org",
        )

    with raises(ValueError, match="'valid_until' must be later than 'valid_from'"):
        ClaimCreation(
            user_id="foo",
            visa_type=VisaType.RESEARCHER_STATUS,
            visa_value="foo@bar.org",
            assertion_date=datetime(2022, 9, 1, 12, 0, tzinfo=UTC),
            valid_from=valid_from,
            valid_until=valid_from,
            source="https://foo.org",
        )
