import datetime
import random
import uuid
from typing import Dict
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from ee.clickhouse.models.event import create_event
from freezegun import freeze_time
from multi_tenancy.models import OrganizationBilling, Plan
from posthog.api.test.base import APIBaseTest, BaseTest, TransactionBaseTest
from posthog.models import User
from rest_framework import status

from .base import PlanTestMixin


class TestPlan(BaseTest):
    def test_cannot_create_plan_without_required_attributes(self):
        with self.assertRaises(ValidationError) as e:
            Plan.objects.create()

        self.assertEqual(
            e.exception.message_dict,
            {
                "key": ["This field cannot be blank."],
                "name": ["This field cannot be blank."],
                "price_id": ["This field cannot be blank."],
            },
        )

    def test_plan_has_unlimited_event_allowance_by_default(self):
        plan = Plan.objects.create(key="test_plan", name="Test Plan", price_id="price_test")
        self.assertEqual(plan.event_allowance, None)


class TestOrganizationBilling(BaseTest, PlanTestMixin):
    def test_billing_is_active(self):

        plan = self.create_plan()
        organization, _, _ = self.create_org_team_user()

        billing = OrganizationBilling.objects.create(organization=organization, should_setup_billing=True,)

        # Active billing
        self.assertEqual(billing.is_billing_active, False)
        billing.should_setup_billing = False
        billing.billing_period_ends = timezone.now() + datetime.timedelta(seconds=30)
        billing.plan = plan
        billing.save()
        self.assertEqual(billing.is_billing_active, True)

        # No plan
        billing.plan = None
        billing.save()
        self.assertEqual(billing.is_billing_active, False)

        # Has not finished setting up billing
        billing.plan = plan
        billing.should_setup_billing = True
        billing.save()
        self.assertEqual(billing.is_billing_active, False)

        # Expired billing
        billing.should_setup_billing = False
        billing.billing_period_ends = timezone.now() - datetime.timedelta(seconds=30)
        billing.save()
        self.assertEqual(billing.is_billing_active, False)

    def test_plan_key_method(self):
        plan = self.create_plan()
        organization, _, _ = self.create_org_team_user()

        billing = OrganizationBilling.objects.create(organization=organization, should_setup_billing=True,)

        # No plan
        self.assertEqual(billing.get_plan_key(), None)

        # Plan but subscription is not active
        billing.plan = plan
        billing.save()
        self.assertEqual(billing.get_plan_key(), None)

        # Plan but subscription is expired
        billing.billing_period_ends = timezone.now() - datetime.timedelta(seconds=30)
        billing.save()
        self.assertEqual(billing.get_plan_key(), None)

        # Active plan
        billing.billing_period_ends = timezone.now() + datetime.timedelta(seconds=30)
        billing.should_setup_billing = False
        billing.save()
        self.assertEqual(billing.get_plan_key(), plan.key)

    def test_available_features(self):
        plan = self.create_plan(key="starter")
        organization, _, _ = self.create_org_team_user()

        # No plan
        billing = OrganizationBilling.objects.create(organization=organization,)
        self.assertEqual(billing.available_features, [])

        # Inactive plan
        billing.plan = plan
        billing.save()
        self.assertEqual(billing.available_features, [])

        # Expired plan
        billing.billing_period_ends = timezone.now() - datetime.timedelta(seconds=30)
        billing.save()
        self.assertEqual(billing.available_features, [])

        # Active plan (starter)
        billing.billing_period_ends = timezone.now() + datetime.timedelta(seconds=30)
        billing.save()
        self.assertEqual(billing.available_features, ["organizations_projects"])

        # Startup plan
        plan.key = "startup"
        plan.save()
        self.assertIn("organizations_projects", billing.available_features)
        self.assertIn("zapier", billing.available_features)

        # Growth plan
        plan.key = "growth"
        plan.save()
        self.assertIn("organizations_projects", billing.available_features)

        # Standard plan
        plan.key = "standard"
        plan.save()
        self.assertIn("organizations_projects", billing.available_features)
        self.assertIn("zapier", billing.available_features)

        # Enterprise plan
        plan.key = "enterprise"
        plan.save()
        self.assertIn("organizations_projects", billing.available_features)
        self.assertIn("zapier", billing.available_features)

    def test_feature_available_multi_tenancy(self):
        organization, _, _ = self.create_org_team_user()
        plan = self.create_plan(key="starter")
        billing = OrganizationBilling.objects.create(organization=organization, plan=plan,)

        # Inactive billing period
        self.assertFalse(organization.is_feature_available("organizations_projects"))

        # Active plan
        billing.billing_period_ends = timezone.now() + datetime.timedelta(seconds=30)
        billing.save()
        self.assertTrue(organization.is_feature_available("organizations_projects"))

        # Unavailable feature
        self.assertFalse(organization.is_feature_available("zapier"))

    def test_event_allocation_property(self):
        organization, _, _ = self.create_org_team_user()
        billing = OrganizationBilling.objects.create(organization=organization,)

        # Defaults to no event allocation, which in turn defaults to None
        self.assertEqual(billing.event_allocation, None)

        with self.settings(BILLING_NO_PLAN_EVENT_ALLOCATION=133):
            self.assertEqual(billing.event_allocation, 133)

        # Still defaults to no plan allocation because plan is not active
        plan = self.create_plan(key="starter", event_allowance=7777)
        billing.plan = plan
        billing.save()
        with self.settings(BILLING_NO_PLAN_EVENT_ALLOCATION=133):
            self.assertEqual(billing.event_allocation, 133)

        # Plan is now active
        billing.billing_period_ends = timezone.now() + datetime.timedelta(days=4)
        billing.save()
        with self.settings(BILLING_NO_PLAN_EVENT_ALLOCATION=133):
            self.assertEqual(billing.event_allocation, 7777)


class TestAPIOrganizationBilling(TransactionBaseTest, PlanTestMixin):

    TESTS_API = True

    # Setting up billing

    def test_team_should_not_set_up_billing_by_default(self):

        count: int = OrganizationBilling.objects.count()
        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(
            response_data["billing"], {"plan": None, "current_usage": 0, "event_allocation": None},
        )

        # OrganizationBilling object should've been created if non-existent
        self.assertEqual(OrganizationBilling.objects.count(), count + 1)
        org_billing: OrganizationBilling = OrganizationBilling.objects.get(organization=self.organization,)

        # Test default values for OrganizationBilling
        self.assertEqual(org_billing.should_setup_billing, False)
        self.assertEqual(org_billing.stripe_customer_id, "")
        self.assertEqual(org_billing.stripe_checkout_session, "")

    def test_provide_event_allocation_for_when_no_billing_plan_is_setup(self):

        with self.settings(BILLING_NO_PLAN_EVENT_ALLOCATION=7500):
            response = self.client.post("/api/user/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(
            response_data["billing"], {"plan": None, "current_usage": 0, "event_allocation": 7500},
        )

    def test_team_that_should_not_set_up_billing(self):
        organization, team, user = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=False,
        )
        self.client.force_login(user)

        for _ in range(0, 3):
            # Create some events on CH
            create_event(
                team=team, event="$pageview", distinct_id="distinct_id", event_uuid=uuid.uuid4(),
            )

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(
            response_data["billing"], {"plan": None, "current_usage": 3, "event_allocation": None},
        )

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_team_that_should_set_up_billing_starts_a_checkout_session(
        self, mock_customer_id,
    ):
        mock_customer_id.return_value = "cus_000111222"
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(custom_setup_billing_message="Sign up now!", event_allowance=50000,)
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, plan=plan,
        )
        self.client.force_login(user)

        with self.assertLogs("multi_tenancy.stripe") as log:

            response = self.client.post("/api/user/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertIn(
                "cus_000111222", log.output[0],
            )  # customer ID is included in the payload to Stripe

            self.assertIn(
                plan.price_id, log.output[0],
            )  # Correct price ID is used

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_1234567890",
        )
        self.assertEqual(
            response_data["billing"]["subscription_url"], "/billing/setup?session_id=cs_1234567890",
        )

        self.assertEqual(
            response_data["billing"]["plan"],
            {
                "key": plan.key,
                "name": plan.name,
                "custom_setup_billing_message": "Sign up now!",
                "event_allowance": 50000,
                "image_url": "",
                "self_serve": False,
                "is_metered_billing": False,
                "price_string": "",
            },
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, response_data["billing"]["stripe_checkout_session"],
        )
        self.assertEqual(instance.stripe_customer_id, "cus_000111222")

    @patch("multi_tenancy.stripe._get_customer_id")
    @patch("multi_tenancy.stripe.stripe.checkout.Session.create")
    def test_startup_team_starts_checkout_session(
        self, mock_checkout, mock_customer_id,
    ):
        """
        Startup is handled with custom logic, because only a validation charge is made
        instead of setting up a full subscription.
        """

        mock_customer_id.return_value = "cus_000111222"
        mock_cs_session = MagicMock()
        mock_cs_session.id = "cs_1234567890"

        mock_checkout.return_value = mock_cs_session
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(key="startup")
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, plan=plan,
        )
        self.client.force_login(user)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert that Stripe was called with the correct data
        mock_checkout.assert_called_once_with(
            customer="cus_000111222",
            line_items=[{"amount": 50, "quantity": 1, "currency": "USD", "name": "Card authorization",}],
            mode="payment",
            payment_intent_data={
                "capture_method": "manual",
                "statement_descriptor": "POSTHOG PREAUTH",
                "setup_future_usage": "off_session",
            },
            payment_method_types=["card"],
            success_url="http://testserver/billing/welcome?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://testserver/billing/failed?session_id={CHECKOUT_SESSION_ID}",
        )

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_1234567890",
        )
        self.assertEqual(
            response_data["billing"]["subscription_url"], "/billing/setup?session_id=cs_1234567890",
        )

        self.assertEqual(
            response_data["billing"]["plan"],
            {
                "key": "startup",
                "name": plan.name,
                "custom_setup_billing_message": "",
                "event_allowance": None,
                "image_url": "",
                "self_serve": False,
                "is_metered_billing": False,
                "price_string": "",
            },
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, "cs_1234567890",
        )
        self.assertEqual(instance.stripe_customer_id, "cus_000111222")

    @patch("multi_tenancy.stripe._get_customer_id")
    @patch("multi_tenancy.stripe.stripe.checkout.Session.create")
    def test_start_checkout_session_for_metered_billing_plan(
        self, mock_checkout, mock_customer_id,
    ):
        """
        Tests that a checkout session is properly created for a metered-billing plan
        (only card setup for future usage is set up at this stage; no subscription is created)
        """

        mock_customer_id.return_value = "cus_000111222"
        mock_cs_session = MagicMock()
        mock_cs_session.id = "cs_usage_1234567890"

        mock_checkout.return_value = mock_cs_session
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(key="usage1", is_metered_billing=True)
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, plan=plan,
        )
        self.client.force_login(user)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert that Stripe was called with the correct data
        mock_checkout.assert_called_once_with(
            customer="cus_000111222",
            line_items=[{"amount": 50, "quantity": 1, "currency": "USD", "name": "Card authorization",}],
            mode="payment",
            payment_intent_data={
                "capture_method": "manual",
                "statement_descriptor": "POSTHOG PREAUTH",
                "setup_future_usage": "off_session",
            },
            payment_method_types=["card"],
            success_url="http://testserver/billing/welcome?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://testserver/billing/failed?session_id={CHECKOUT_SESSION_ID}",
        )

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_usage_1234567890",
        )
        self.assertEqual(
            response_data["billing"]["subscription_url"], "/billing/setup?session_id=cs_usage_1234567890",
        )

        self.assertEqual(
            response_data["billing"]["plan"],
            {
                "key": "usage1",
                "name": plan.name,
                "custom_setup_billing_message": "",
                "event_allowance": None,
                "image_url": "",
                "self_serve": False,
                "is_metered_billing": True,
                "price_string": "",
            },
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, "cs_usage_1234567890",
        )
        self.assertEqual(instance.stripe_customer_id, "cus_000111222")

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_already_active_checkout_session_uses_same_session(
        self, mock_customer_id,
    ):
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            plan=plan,
            stripe_checkout_session="cs_987654321",
            checkout_session_created_at=timezone.now() - timezone.timedelta(hours=23),
        )
        self.client.force_login(user)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_987654321",  # <- same session
        )
        mock_customer_id.assert_not_called()  # Stripe is not called
        self.assertEqual(
            response_data["billing"]["subscription_url"], "/billing/setup?session_id=cs_987654321",
        )

        # Check that the checkout session does not change
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, response_data["billing"]["stripe_checkout_session"],
        )

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_expired_checkout_session_generates_a_new_one(
        self, mock_customer_id,
    ):
        mock_customer_id.return_value = "cus_000111222"
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            plan=plan,
            stripe_checkout_session="cs_ABCDEFGHIJ",
            checkout_session_created_at=timezone.now() - timezone.timedelta(hours=24, minutes=2),
        )
        self.client.force_login(user)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_1234567890",  # <- note the different session
        )
        mock_customer_id.assert_called_once()

        # Assert that the new checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, response_data["billing"]["stripe_checkout_session"],
        )

    def test_cannot_start_double_billing_subscription(self):
        organization, _, user = self.create_org_team_user()
        plan = self.create_plan(
            event_allowance=8_500_000, image_url="http://test.posthog.com/image.png", self_serve=True,
        )
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=False,
            plan=plan,
            billing_period_ends=timezone.now() + timezone.timedelta(minutes=random.randint(10, 99)),
        )
        self.client.force_login(user)

        # Make sure the billing is already active
        self.assertEqual(instance.is_billing_active, True)

        response_data = self.client.post("/api/user/").json()

        self.assertEqual(
            response_data["billing"]["plan"],
            {
                "key": plan.key,
                "name": plan.name,
                "custom_setup_billing_message": "",
                "event_allowance": 8500000,
                "image_url": "http://test.posthog.com/image.png",
                "self_serve": True,
                "is_metered_billing": False,
                "price_string": "",
            },
        )

    def test_silent_fail_if_stripe_variables_are_not_properly_configured(self):
        """
        If Stripe variables are not properly set, an exception will be sent to Sentry.
        """

        organization, team, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, plan=self.create_plan(),
        )
        self.client.force_login(user)

        with self.settings(STRIPE_API_KEY=""):
            response_data: Dict = self.client.post("/api/user/").json()

        self.assertNotIn(
            "should_setup_billing", response_data["billing"],
        )

        instance.refresh_from_db()
        self.assertEqual(instance.stripe_checkout_session, "")

    @patch("multi_tenancy.utils.get_cached_monthly_event_usage")
    def test_event_usage_is_cached(self, mock_method):
        organization, team, user = self.create_org_team_user()
        self.client.force_login(user)

        # Org has no events, but cached result is used
        cache.set(f"monthly_usage_{organization.id}", 4831, 10)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert that the uncached method was not called
        mock_method.assert_not_called()

        response_data: Dict = response.json()
        self.assertEqual(
            response_data["billing"], {"plan": None, "event_allocation": None, "current_usage": 4831},
        )

    @freeze_time("2018-12-31T22:59:59.000000Z")
    def test_event_usage_cache_is_reset_at_beginning_of_month(self):
        organization, team, user = self.create_org_team_user()
        self.client.force_login(user)

        for _ in range(0, 3):
            # Create some events on CH
            create_event(
                team=team, event="$pageview", distinct_id="distinct_id", event_uuid=uuid.uuid4(),
            )

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["billing"]["current_usage"], 3)

        # Check that result was cached
        cache_key = f"monthly_usage_{organization.id}"
        self.assertEqual(cache.get(cache_key), 3)

        # Even though default caching time is 12 hours, the result is only cached until beginning of next month
        self.assertEqual(
            cache._expire_info.get(cache.make_key(cache_key)), 1546300800.0,
        )  # 1546300800 = Jan 1, 2019 00:00 UTC

    def test_user_with_no_org(self):
        """
        Tests the edge case of user not belonging to any organization to make sure the `/api/user` request is handled
        gracefully.
        """

        user = User.objects.create(email="alone@posthog.com")
        self.client.force_login(user)
        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data: Dict = response.json()
        self.assertEqual(response_data["organization"], None)
        self.assertEqual(response_data["email"], "alone@posthog.com")

    # Manage billing

    def test_user_can_manage_billing(self):

        organization, team, user = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, stripe_customer_id="cus_12345678",
        )
        self.client.force_login(user)

        with self.settings(STRIPE_API_KEY="sk_test_987654321"):
            response = self.client.post("/billing/manage")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, "/manage-my-billing/cus_12345678")

    def test_logged_out_user_cannot_manage_billing(self):

        self.client.logout()
        response = self.client.post("/billing/manage")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_with_no_billing_set_up_cannot_manage_it(self):

        organization, team, user = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True,
        )
        self.client.force_login(user)

        response = self.client.post("/billing/manage")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, "/")

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_organization_can_enroll_in_self_serve_plan(self, mock_customer_id):
        mock_customer_id.return_value = "cus_000111222"
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(self_serve=True)

        org_billing = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, plan=self.create_plan(),
        )  # note the org has another plan configured but no active billing subscription

        self.client.force_login(user)

        response = self.client.post("/billing/subscribe", {"plan": plan.key})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data,
            {
                "stripe_checkout_session": "cs_1234567890",
                "subscription_url": "/billing/setup?session_id=cs_1234567890",
            },
        )

        org_billing.refresh_from_db()
        self.assertEqual(org_billing.stripe_checkout_session, "cs_1234567890")
        self.assertEqual(org_billing.stripe_customer_id, "cus_000111222")
        self.assertEqual(org_billing.plan, plan)
        self.assertTrue((timezone.now() - org_billing.checkout_session_created_at).total_seconds() <= 2,)

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_organization_can_enroll_in_self_serve_plan_without_having_an_organization_billing_yet(
        self, mock_customer_id,
    ):
        mock_customer_id.return_value = "cus_000111222"
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(self_serve=True)

        self.client.force_login(user)

        response = self.client.post("/billing/subscribe", {"plan": plan.key})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data,
            {
                "stripe_checkout_session": "cs_1234567890",
                "subscription_url": "/billing/setup?session_id=cs_1234567890",
            },
        )

        org_billing = organization.billing
        self.assertEqual(org_billing.stripe_checkout_session, "cs_1234567890")
        self.assertEqual(org_billing.stripe_customer_id, "cus_000111222")
        self.assertEqual(org_billing.plan, plan)
        self.assertEqual(org_billing.should_setup_billing, True)
        self.assertTrue((timezone.now() - org_billing.checkout_session_created_at).total_seconds() <= 2,)

    def test_cannot_enroll_in_non_self_serve_plan(self):
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(self_serve=False)

        org_billing = OrganizationBilling.objects.create(organization=organization)

        self.client.force_login(user)

        response = self.client.post("/billing/subscribe", {"plan": plan.key})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        org_billing.refresh_from_db()
        self.assertEqual(org_billing.plan, None)
        self.assertEqual(org_billing.stripe_checkout_session, "")
        self.assertEqual(org_billing.stripe_customer_id, "")
        self.assertEqual(org_billing.checkout_session_created_at, None)


class PlanAPITestCase(APIBaseTest, PlanTestMixin):
    def setUp(self):
        super().setUp()

        for _ in range(0, 3):
            self.create_plan()

        self.create_plan(is_active=False)
        self.create_plan(event_allowance=49334, self_serve=True)

    def test_listing_and_retrieving_plans(self):
        response = self.client.get("/api/plans")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["count"], Plan.objects.exclude(is_active=False).count(),
        )

        for item in response.data["results"]:
            obj = Plan.objects.get(key=item["key"])

            self.assertEqual(
                list(item.keys()),
                [
                    "key",
                    "name",
                    "custom_setup_billing_message",
                    "event_allowance",
                    "image_url",
                    "self_serve",
                    "is_metered_billing",
                    "price_string",
                ],
            )

            self.assertEqual(item["event_allowance"], 49334 if obj.event_allowance else None)

            retrieve_response = self.client.get(f"/api/plans/{obj.key}")
            self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                retrieve_response.data, item,
            )  # Retrieve response is equal to list response

    def test_list_self_serve_plans(self):
        response = self.client.get("/api/plans?self_serve=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["count"], Plan.objects.exclude(is_active=False).exclude(self_serve=False).count(),
        )

        for item in response.data["results"]:
            obj = Plan.objects.get(key=item["key"])

            self.assertEqual(
                list(item.keys()),
                [
                    "key",
                    "name",
                    "custom_setup_billing_message",
                    "event_allowance",
                    "image_url",
                    "self_serve",
                    "is_metered_billing",
                    "price_string",
                ],
            )
            self.assertEqual(obj.self_serve, True)

    def test_inactive_plans_cannot_be_retrieved(self):
        plan = self.create_plan(is_active=False)
        response = self.client.get(f"/api/plans/{plan.key}")
        self.assertEqual(
            response.json(), {"attr": None, "code": "not_found", "detail": "Not found.", "type": "invalid_request",},
        )

    def test_get_plan_template(self):
        """
        Tests that anyone can obtain the plan details.
        """
        self.create_plan(key="standard")
        self.client.logout()

        f = open("multi_tenancy/templates/plans/standard.html", "r")
        expected = f.read()
        f.close()

        response = self.client.get("/api/plans/standard/template/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content.decode(), expected)

    def test_empty_template_for_plan_or_inexistent_plan(self):

        self.client.logout()

        # Plan has no template
        self.create_plan(key="new_plan")
        response = self.client.get("/api/plans/new_plan/template/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

        # Plan is not active
        self.create_plan(key="starter", is_active=False)
        response = self.client.get("/api/plans/new_plan/template/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

        # Plan does not exist
        response = self.client.get("/api/plans/im_inavlid/template/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

    def test_cannot_update_plans(self):
        plan = self.create_plan()

        # PUT UPDATE
        response = self.client.put(f"/api/plans/{plan.key}", {"price_id": "new_pricing"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        plan.refresh_from_db()
        self.assertNotEqual(plan.price_id, "new_pricing")

        # PATCH UPDATE
        response = self.client.patch(f"/api/plans/{plan.key}", {"price_id": "new_pricing"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        plan.refresh_from_db()
        self.assertNotEqual(plan.price_id, "new_pricing")
