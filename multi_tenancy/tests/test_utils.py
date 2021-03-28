import datetime

import pytz
from django.utils import timezone
from freezegun import freeze_time
from multi_tenancy.tests.base import CloudBaseTest
from multi_tenancy.utils import get_billing_cycle_anchor, get_event_usage_for_timerange
from posthog.models import Team


class TestUtils(CloudBaseTest):
    def test_get_billing_cycle_anchor(self):

        with freeze_time("2020-01-01"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S"), "2020-01-01T23:59:59",
            )

        with freeze_time("2020-01-02"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"), "2020-02-01",
            )

        with freeze_time("2020-01-18"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"), "2020-02-01",
            )

        with freeze_time("2020-01-31"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S"), "2020-02-01T23:59:59",
            )

    def test_get_billing_cycle_anchor_with_trial_date(self):
        with self.settings(BILLING_TRIAL_DAYS=30):

            with freeze_time("2021-03-01"):
                self.assertEqual(
                    get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S"), "2021-04-01T23:59:59",
                )

            with freeze_time("2021-03-03"):
                self.assertEqual(
                    get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"),
                    "2021-05-01",  # because March has 31 days, the trial will end on the 2nd
                )

            with freeze_time("2021-03-04"):
                self.assertEqual(
                    get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"), "2021-05-01",
                )

    def test_get_event_usage_for_timerange(self):

        org, team, _ = self.create_org_team_user()
        team2 = Team.objects.create(organization=org)
        another_org, another_team, _ = self.create_org_team_user()

        # Set up some events
        with freeze_time("2020-03-02"):
            self.event_factory(team, 4)
            self.event_factory(team2, 3)
            self.event_factory(another_team, 8)

        with freeze_time("2020-03-03"):
            self.event_factory(team, 2)
            self.event_factory(team2, 1)

        self.assertEqual(
            get_event_usage_for_timerange(
                org,
                datetime.datetime(2020, 3, 2, 0, 0, 0, 0, pytz.UTC),
                datetime.datetime(2020, 3, 2, 23, 59, 59, 999999, pytz.UTC),
            ),
            7,  # 4 from team & 3 from team2
        )

        self.assertEqual(
            get_event_usage_for_timerange(
                org,
                datetime.datetime(2020, 3, 2, 0, 0, 0, 0, pytz.UTC),
                datetime.datetime(2020, 3, 3, 23, 59, 59, 999999, pytz.UTC),
            ),
            10,
        )

        self.assertEqual(
            get_event_usage_for_timerange(
                another_org,
                datetime.datetime(2020, 3, 1, 0, 0, 0, 0, pytz.UTC),
                datetime.datetime(2020, 3, 31, 23, 59, 59, 999999, pytz.UTC),
            ),
            8,
        )

