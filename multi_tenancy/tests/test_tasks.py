import datetime
from unittest.mock import patch

import pytz
from freezegun import freeze_time
from multi_tenancy.models import OrganizationBilling, Plan
from multi_tenancy.tasks import compute_daily_usage_for_organizations
from multi_tenancy.tests.base import CloudBaseTest


class TestTasks(CloudBaseTest):
    @freeze_time("2020-05-07")
    @patch("multi_tenancy.stripe._init_stripe")
    @patch("multi_tenancy.stripe.stripe.SubscriptionItem.create_usage_record")
    def test_compute_daily_usage_for_organizations(self, mock_create_usage_record, _):
        plan = Plan.objects.create(key="metered", name="Metered", price_id="m1", is_metered_billing=True)
        org, team, _ = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=org, stripe_subscription_item_id="si_1111111111111", plan=plan,
        )
        another_org, another_team, _ = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=another_org, stripe_subscription_item_id="si_01234567890", plan=plan,
        )

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
        self.assertEqual(mock_create_usage_record.call_args_list[0].args, ("si_1111111111111",))
        self.assertEqual(mock_create_usage_record.call_args_list[0].kwargs["quantity"], 14)
        self.assertEqual(
            mock_create_usage_record.call_args_list[0].kwargs["idempotency_key"], "si_1111111111111-2020-05-06",
        )

        # another team
        self.assertEqual(mock_create_usage_record.call_args_list[1].args, ("si_01234567890",))
        self.assertEqual(mock_create_usage_record.call_args_list[1].kwargs["quantity"], 11)
        self.assertEqual(
            mock_create_usage_record.call_args_list[1].kwargs["idempotency_key"], "si_01234567890-2020-05-06",
        )

    @patch("multi_tenancy.tasks._compute_daily_usage_for_organization")
    def test_only_rerport_relevant_usage_for_organizations(self, mock_individual_org_task):
        plan = Plan.objects.create(key="unmetered", price_id="u1", name="Flat fee")
        org, _, _ = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=org, stripe_subscription_item_id="si_1111111111111", plan=plan,
        )  # non-metered plan
        another_org, _, _ = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=another_org, plan=plan,
        )  # no subscription item ID plan
        _, _, _ = self.create_org_team_user()  # no OrganizationBilling

        compute_daily_usage_for_organizations()
        mock_individual_org_task.assert_not_called()

    @freeze_time("2020-11-11")
    @patch("multi_tenancy.stripe._init_stripe")
    @patch("multi_tenancy.stripe.stripe.SubscriptionItem.create_usage_record")
    def test_compute_daily_usage_for_different_date(self, mock_create_usage_record, _):
        plan = Plan.objects.create(key="metered", name="Metered", price_id="m1", is_metered_billing=True)
        org, team, _ = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=org, stripe_subscription_item_id="si_1111111111111", plan=plan,
        )
        # Some noise events that should be ignored
        with freeze_time("2020-11-11"):  # today
            self.event_factory(team, 4)
        with freeze_time("2020-11-10"):  # yesterday
            self.event_factory(team, 6)
        with freeze_time("2020-11-09"):  # 2 days ago
            self.event_factory(team, 1)

        # Now some real events
        with freeze_time("2020-11-03T09:39:12"):
            self.event_factory(team, 5)

        with freeze_time("2020-11-03T12:59:45"):
            self.event_factory(team, 11)

        compute_daily_usage_for_organizations(datetime.datetime(2020, 11, 3, tzinfo=pytz.UTC))
        self.assertEqual(mock_create_usage_record.call_count, 1)

        self.assertEqual(mock_create_usage_record.call_args_list[0].args, ("si_1111111111111",))
        self.assertEqual(mock_create_usage_record.call_args_list[0].kwargs["quantity"], 16)
        self.assertEqual(
            mock_create_usage_record.call_args_list[0].kwargs["idempotency_key"], "si_1111111111111-2020-11-03",
        )
