import random

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from multi_tenancy.models import Plan
from multi_tenancy.utils import get_billing_cycle_anchor
from posthog.models import User


class PlanTestMixin:
    def create_org_team_user(self):
        return User.objects.bootstrap(
            company_name="Z",
            first_name="X",
            email=f"user{random.randint(100, 999)}@posthog.com",
            password=self.TESTS_PASSWORD,
            team_fields={"api_token": "token789"},
        )

    def create_plan(self, **kwargs):
        return Plan.objects.create(
            **{
                "key": f"plan_{random.randint(100000, 999999)}",
                "price_id": f"price_{random.randint(1000000, 9999999)}",
                "name": "Test Plan",
                **kwargs,
            },
        )


class UtilsTest(TestCase):
    def test_get_billing_cycle_anchor(self):

        with freeze_time("2020-01-1"):
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
