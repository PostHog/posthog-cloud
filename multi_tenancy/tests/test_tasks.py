from unittest.mock import patch

from django.test.testcases import TestCase
from freezegun import freeze_time
from multi_tenancy.models import OrganizationBilling
from multi_tenancy.tasks import compute_daily_usage_for_organizations
from multi_tenancy.tests.base import FactoryMixin


class TestTasks(TestCase, FactoryMixin):
    @freeze_time("2020-05-07")
    @patch("multi_tenancy.stripe.stripe.SubscriptionItem.create_usage_record")
    def test_compute_daily_usage_for_organizations(self, mock_create_usage_record):
        org, team = self.create_org_and_team()
        OrganizationBilling.objects.create(
            organization=org, stripe_subscription_item_id="si_1111111111111"
        )
        another_org, another_team = self.create_org_and_team()
        OrganizationBilling.objects.create(
            organization=another_org, stripe_subscription_item_id="si_01234567890"
        )
        _, unbilled_team = self.create_org_and_team()

        # Some noise events that should be ignored
        with freeze_time("2020-05-07"):  # today
            self.event_factory(team, 4)
            self.event_factory(another_team, 3)
        with freeze_time("2020-05-05"):  # 2 days ago
            self.event_factory(team, 6)
            self.event_factory(another_team, 5)
        with freeze_time("2020-05-08"):  # tomorrow
            self.event_factory(team, 1)
            self.event_factory(another_team, 1)
        self.event_factory(unbilled_team, 3)

        # Now some real events
        with freeze_time("2020-05-06T04:39:12"):
            self.event_factory(another_team, 6)
            self.event_factory(team, 3)

        with freeze_time("2020-05-06T23:59:45"):
            self.event_factory(another_team, 5)
            self.event_factory(team, 11)

        compute_daily_usage_for_organizations()
        self.assertEqual(mock_create_usage_record.call_count, 2)

        # team
        self.assertEqual(
            mock_create_usage_record.call_args_list[0].args, ("si_1111111111111",)
        )
        self.assertEqual(
            mock_create_usage_record.call_args_list[0].kwargs["quantity"], 14
        )
        self.assertEqual(
            mock_create_usage_record.call_args_list[0].kwargs["idempotency_key"],
            "si_1111111111111-2020-05-06",
        )

        # another team
        self.assertEqual(
            mock_create_usage_record.call_args_list[1].args, ("si_01234567890",)
        )
        self.assertEqual(
            mock_create_usage_record.call_args_list[1].kwargs["quantity"], 11
        )
        self.assertEqual(
            mock_create_usage_record.call_args_list[1].kwargs["idempotency_key"],
            "si_01234567890-2020-05-06",
        )
