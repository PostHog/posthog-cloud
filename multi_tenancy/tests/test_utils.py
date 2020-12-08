from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from multi_tenancy.utils import get_billing_cycle_anchor


class TestUtils(TestCase):
    def test_get_billing_cycle_anchor(self):

        with freeze_time("2020-01-01"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S"),
                "2020-01-02T23:59:59",
            )

        with freeze_time("2020-01-02"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"),
                "2020-01-02",
            )

        with freeze_time("2020-01-03"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"),
                "2020-02-02",
            )

        with freeze_time("2020-01-18"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"),
                "2020-02-02",
            )

        with freeze_time("2020-01-31"):
            self.assertEqual(
                get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S"),
                "2020-02-02T23:59:59",
            )

    def test_get_billing_cycle_anchor_with_trial_date(self):
        with self.settings(BILLING_TRIAL_DAYS=30):

            with freeze_time("2021-03-01"):
                self.assertEqual(
                    get_billing_cycle_anchor(timezone.now()).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                    "2021-04-02T23:59:59",
                )

            with freeze_time("2021-03-03"):
                self.assertEqual(
                    get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"),
                    "2021-04-02",  # because March has 31 days, the trial will end on the 2nd
                )

            with freeze_time("2021-03-04"):
                self.assertEqual(
                    get_billing_cycle_anchor(timezone.now()).strftime("%Y-%m-%d"),
                    "2021-05-02",
                )
