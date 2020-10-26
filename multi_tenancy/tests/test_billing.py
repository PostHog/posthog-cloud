import datetime
import random
from typing import Dict
from unittest.mock import MagicMock, patch

import pytz
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from freezegun import freeze_time
from multi_tenancy.models import OrganizationBilling, Plan
from multi_tenancy.stripe import compute_webhook_signature
from posthog.api.test.base import APIBaseTest, BaseTest, TransactionBaseTest
from posthog.models import Event, User
from rest_framework import status


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
        plan = Plan.objects.create(
            key="test_plan", name="Test Plan", price_id="price_test"
        )
        self.assertEqual(plan.event_allowance, None)


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


class TestOrganizationBilling(TransactionBaseTest, PlanTestMixin):

    TESTS_API = True

    # Setting up billing

    def test_team_should_not_set_up_billing_by_default(self):

        count: int = OrganizationBilling.objects.count()
        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(
            response_data["billing"],
            {"plan": None, "current_usage": {"formatted": "0", "value": 0}},
        )

        # OrganizationBilling object should've been created if non-existent
        self.assertEqual(OrganizationBilling.objects.count(), count + 1)
        org_billing: OrganizationBilling = OrganizationBilling.objects.get(
            organization=self.organization,
        )

        # Test default values for OrganizationBilling
        self.assertEqual(org_billing.should_setup_billing, False)
        self.assertEqual(org_billing.stripe_customer_id, "")
        self.assertEqual(org_billing.stripe_checkout_session, "")

    def test_team_that_should_not_set_up_billing(self):
        organization, team, user = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=False,
        )
        self.client.force_login(user)

        for _ in range(0, 3):
            Event.objects.create(team=team)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(
            response_data["billing"],
            {"plan": None, "current_usage": {"value": 3, "formatted": "3"}},
        )

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_team_that_should_set_up_billing_starts_a_checkout_session(
        self, mock_customer_id,
    ):
        mock_customer_id.return_value = "cus_000111222"
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(
            custom_setup_billing_message="Sign up now!", event_allowance=50000
        )
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
            response_data["billing"]["subscription_url"],
            "/billing/setup?session_id=cs_1234567890",
        )

        self.assertEqual(
            response_data["billing"]["plan"],
            {
                "key": plan.key,
                "name": plan.name,
                "custom_setup_billing_message": "Sign up now!",
                "allowance": {"value": 50000, "formatted": "50K"},
                "image_url": "",
                "self_serve": False,
            },
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session,
            response_data["billing"]["stripe_checkout_session"],
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
            line_items=[
                {
                    "amount": 50,
                    "quantity": 1,
                    "currency": "USD",
                    "name": "Card authorization",
                }
            ],
            mode="payment",
            payment_intent_data={
                "capture_method": "manual",
                "statement_descriptor": "POSTHOG PREAUTH",
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
            response_data["billing"]["subscription_url"],
            "/billing/setup?session_id=cs_1234567890",
        )

        self.assertEqual(
            response_data["billing"]["plan"],
            {
                "key": "startup",
                "name": plan.name,
                "custom_setup_billing_message": "",
                "allowance": None,
                "image_url": "",
                "self_serve": False,
            },
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, "cs_1234567890",
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
            response_data["billing"]["stripe_checkout_session"],
            "cs_987654321",  # <- same session
        )
        mock_customer_id.assert_not_called()  # Stripe is not called
        self.assertEqual(
            response_data["billing"]["subscription_url"],
            "/billing/setup?session_id=cs_987654321",
        )

        # Check that the checkout session does not change
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session,
            response_data["billing"]["stripe_checkout_session"],
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
            checkout_session_created_at=timezone.now()
            - timezone.timedelta(hours=24, minutes=2),
        )
        self.client.force_login(user)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"],
            "cs_1234567890",  # <- note the different session
        )
        mock_customer_id.assert_called_once()

        # Assert that the new checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session,
            response_data["billing"]["stripe_checkout_session"],
        )

    def test_cannot_start_double_billing_subscription(self):
        organization, team, user = self.create_org_team_user()
        plan = self.create_plan(
            event_allowance=8_500_000,
            image_url="http://test.posthog.com/image.png",
            self_serve=True,
        )
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            plan=plan,
            billing_period_ends=timezone.now()
            + timezone.timedelta(minutes=random.randint(10, 99)),
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
                "allowance": {"value": 8500000, "formatted": "8.5M"},
                "image_url": "http://test.posthog.com/image.png",
                "self_serve": True,
            },
        )

    def test_silent_fail_if_stripe_variables_are_not_properly_configured(self):
        """
        If Stripe variables are not properly set, an exception will be sent to Sentry.
        """

        organization, team, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            plan=self.create_plan(),
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
            response_data["billing"],
            {"plan": None, "current_usage": {"value": 4831, "formatted": "4.8K"}},
        )

    @freeze_time("2018-12-31T22:59:59.000000Z")
    def test_event_usage_cache_is_reset_at_beginning_of_month(self):
        organization, team, user = self.create_org_team_user()
        self.client.force_login(user)

        for _ in range(0, 3):
            Event.objects.create(team=team)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["billing"]["current_usage"]["value"], 3)

        # Check that result was cached
        cache_key = f"monthly_usage_{organization.id}"
        self.assertEqual(cache.get(cache_key), 3)

        # Even though default caching time is 12 hours, the result is only cached until beginning of next month
        self.assertEqual(
            cache._expire_info.get(cache.make_key(cache_key)), 1546300800.0,
        )  # 1546300800 = Jan 1, 2019 00:00 UTC

    # Manage billing

    def test_user_can_manage_billing(self):

        organization, team, user = self.create_org_team_user()
        OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_12345678",
        )
        self.client.force_login(user)

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
            organization=organization,
            should_setup_billing=True,
            plan=self.create_plan(),
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
        self.assertTrue(
            (timezone.now() - org_billing.checkout_session_created_at).total_seconds()
            <= 2,
        )

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
        self.assertTrue(
            (timezone.now() - org_billing.checkout_session_created_at).total_seconds()
            <= 2,
        )

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


class TestStripeWebhooks(TransactionBaseTest, PlanTestMixin):
    def generate_webhook_signature(
        self, payload: str, secret: str, timestamp: timezone.datetime = None,
    ) -> str:
        timestamp = timezone.now() if not timestamp else timestamp
        computed_timestamp: int = int(timestamp.timestamp())
        signature: str = compute_webhook_signature(
            "%d.%s" % (computed_timestamp, payload), secret,
        )
        return f"t={computed_timestamp},v1={signature}"

    def test_billing_period_is_updated_when_webhook_is_received(self):

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        organization, team, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_aEDNOHbSpxHcmq",
        )

        # Note that the sample request here does not contain the entire body
        body = """
        {
            "id": "evt_1H2FuICyh3ETxLbCJnSt7FQu",
            "object": "event",
            "created": 1594124897,
            "data": {
                "object": {
                    "id": "in_1H2FuFCyh3ETxLbCNarFj00f",
                    "object": "invoice",
                    "amount_due": 2900,
                    "amount_paid": 2900,
                    "created": 1594124895,
                    "currency": "usd",
                    "custom_fields": null,
                    "customer": "cus_aEDNOHbSpxHcmq",
                    "customer_email": "user440@posthog.com",
                    "lines": {
                        "object": "list",
                            "data": [
                            {
                                "id": "sli_a3c2f4407d4f2f",
                                "object": "line_item",
                                "amount": 2900,
                                "currency": "usd",
                                "description": "1 × PostHog Growth Plan (at $29.00 / month)",
                                "period": {
                                    "end": 1596803295,
                                    "start": 1594124895
                                },
                                "plan": {
                                    "id": "price_1H1zJPCyh3ETxLbCKup83FE0",
                                    "object": "plan",
                                    "nickname": null,
                                    "product": "prod_HbBgfdauoF2CLh"
                                },
                                "price": {
                                    "id": "price_1H1zJPCyh3ETxLbCKup83FE0",
                                    "object": "price"
                                },
                                "quantity": 1,
                                "subscription": "sub_HbSp2C2zNDnw1i",
                                "subscription_item": "si_HbSpBTL6hI03Lp",
                                "type": "subscription",
                                "unique_id": "il_1H2FuFCyh3ETxLbCkOq5TZ5O"
                            }
                        ],
                        "has_more": false,
                        "total_count": 1
                    },
                    "next_payment_attempt": null,
                    "number": "7069031B-0001",
                    "paid": true,
                    "payment_intent": "pi_1H2FuFCyh3ETxLbCjv32zPdu",
                    "period_end": 1594124895,
                    "period_start": 1594124895,
                    "status": "paid",
                    "subscription": "sub_HbSp2C2zNDnw1i"
                }
            },
            "livemode": false,
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(
            enforce_csrf_checks=True,
        )  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):

            response = csrf_client.post(
                "/billing/stripe_webhook",
                body,
                content_type="text/plain",
                HTTP_STRIPE_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that the period end was updated
        instance.refresh_from_db()
        self.assertEqual(
            instance.billing_period_ends,
            timezone.datetime(2020, 8, 7, 12, 28, 15, tzinfo=pytz.UTC),
        )

    @patch("multi_tenancy.views.cancel_payment_intent")
    def test_billing_period_special_handling_for_startup_plan(
        self, cancel_payment_intent,
    ):

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        organization, team, user = self.create_org_team_user()
        startup_plan = Plan.objects.create(
            key="startup", name="Startup", price_id="not_set",
        )
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_I2maGIMVxJI",
            plan=startup_plan,
        )

        # Note that the sample request here does not contain the entire body
        body = """
        {
            "id":"evt_h3ETxFuICyJnLbC1H2St7FQu",
            "object":"event",
            "created":1594124897,
            "data":{
                "object":{
                    "id":"pi_TxLb1HS1CyhnDR",
                    "object":"payment_intent",
                    "status":"requires_capture",
                    "amount":50,
                    "amount_capturable":50,
                    "amount_received":0,
                    "capture_method":"manual",
                    "charges":{
                        "object":"list",
                        "data":[
                        {
                            "id":"ch_1HS204Cyh3ETxLbCkJR5DnKi",
                            "object":"charge"
                        }
                        ],
                        "has_more":true,
                        "total_count":2,
                        "url":"/v1/charges?payment_intent=pi_1HS1wxCyh3ETxLbC5tvUtnDR"
                    },
                    "confirmation_method":"automatic",
                    "created":1600267775,
                    "currency":"usd",
                    "customer":"cus_I2maGIMVxJI",
                    "on_behalf_of":null
                }
            },
            "livemode":false,
            "pending_webhooks":1,
            "type":"payment_intent.amount_capturable_updated"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(
            enforce_csrf_checks=True,
        )  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):

            response = csrf_client.post(
                "/billing/stripe_webhook",
                body,
                content_type="text/plain",
                HTTP_STRIPE_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that the period end was updated (1 year from now)
        instance.refresh_from_db()
        self.assertTrue(
            (
                timezone.now()
                + datetime.timedelta(days=365)
                - instance.billing_period_ends
            ).total_seconds(),
            2,
        )

        # Check that the payment is cancelled (i.e. not captured)
        cancel_payment_intent.assert_called_once_with("pi_TxLb1HS1CyhnDR")

    @patch("multi_tenancy.views.capture_exception")
    def test_webhook_with_invalid_signature_fails(self, capture_exception):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        organization, team, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_bEDNOHbSpxHcmq",
        )

        body = """
        {
            "data": {
                "object": {
                    "id": "in_1H2FuFCyh3ETxLbCNarFj00f",
                    "customer": "cus_bEDNOHbSpxHcmq",
                    "lines": {
                        "object": "list",
                        "data": [
                            {
                                "period": {
                                    "end": 1596803295,
                                    "start": 1594124895
                                }
                            }
                        ]
                    }
                }
            },
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)[
            :-1
        ]  # we remove the last character to make it invalid

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):

            response = self.client.post(
                "/billing/stripe_webhook",
                body,
                content_type="text/plain",
                HTTP_STRIPE_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        capture_exception.assert_called_once()

        # Check that the period end was NOT updated
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, None)

    def test_webhook_with_invalid_payload_fails(self):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        organization, team, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_dEDNOHbSpxHcmq",
        )

        invalid_payload_1: str = "Not a JSON?"

        invalid_payload_2: str = """
        {
            "data": {
                "object": {
                    "id": "in_1H2FuFCyh3ETxLbCNarFj00f",
                    "customer_UNEXPECTED_KEY": "cus_dEDNOHbSpxHcmq",
                    "lines": {
                        "object": "list",
                        "data": [
                            {
                                "period": {
                                    "end": 1596803295,
                                    "start": 1594124895
                                }
                            }
                        ]
                    }
                }
            },
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        for invalid_payload in [invalid_payload_1, invalid_payload_2]:
            signature: str = self.generate_webhook_signature(
                invalid_payload, sample_webhook_secret,
            )

            with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):

                response = self.client.post(
                    "/billing/stripe_webhook",
                    invalid_payload,
                    content_type="text/plain",
                    HTTP_STRIPE_SIGNATURE=signature,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Check that the period end was NOT updated
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, None)

    @patch("multi_tenancy.views.capture_message")
    def test_webhook_where_customer_cannot_be_located_is_logged(self, capture_message):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        body: str = """
        {
            "data": {
                "object": {
                    "id": "in_1H2FuFCyh3ETxLbCNarFj00f",
                    "customer": "cus_12345678",
                    "lines": {
                        "object": "list",
                        "data": [
                            {
                                "period": {
                                    "end": 1596803295,
                                    "start": 1594124895
                                }
                            }
                        ]
                    }
                }
            },
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):
            response = self.client.post(
                "/billing/stripe_webhook",
                body,
                content_type="text/plain",
                HTTP_STRIPE_SIGNATURE=signature,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        capture_message.assert_called_once_with(
            "Received invoice.payment_succeeded for cus_12345678 but customer is not in the database.",
        )

    # TODO
    # def test_feature_available_multi_tenancy(self, patch_organization_billing):
    #     patch_organization_billing.objects.get().price_id = "price_1234567890"
    #     self.assertTrue(self.user.is_feature_available("whatever"))

    # def test_custom_pricing_no_extra_features(self, patch_organization_billing):
    #     patch_organization_billing.objects.get().price_id = (
    #         "price_test_1"  # price_test_1 is not on posthog.models.user.License.PLANS
    #     )
    #     self.assertFalse(self.user.is_feature_available("whatever"))


class PlanTestCase(APIBaseTest, PlanTestMixin):
    def setUp(self):
        super().setUp()

        for _ in range(0, 3):
            self.create_plan()

        self.create_plan(is_active=False)
        self.create_plan(event_allowance=49334, self_serve=True)

    def test_listing_and_retrieving_plans(self):
        response = self.client.get("/plans")
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
                    "allowance",
                    "image_url",
                    "self_serve",
                ],
            )

            if obj.event_allowance:
                self.assertEqual(
                    item["allowance"], {"value": 49334, "formatted": "49.3K"},
                )

            retrieve_response = self.client.get(f"/plans/{obj.key}")
            self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                retrieve_response.data, item,
            )  # Retrieve response is equal to list response

    def test_list_self_serve_plans(self):
        response = self.client.get("/plans?self_serve=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["count"],
            Plan.objects.exclude(is_active=False).exclude(self_serve=False).count(),
        )

        for item in response.data["results"]:
            obj = Plan.objects.get(key=item["key"])

            self.assertEqual(
                list(item.keys()),
                [
                    "key",
                    "name",
                    "custom_setup_billing_message",
                    "allowance",
                    "image_url",
                    "self_serve",
                ],
            )
            self.assertEqual(obj.self_serve, True)

    def test_inactive_plans_cannot_be_retrieved(self):
        plan = self.create_plan(is_active=False)
        response = self.client.get(f"/plans/{plan.key}")
        self.assertEqual(
            response.json(),
            {
                "attr": None,
                "code": "not_found",
                "detail": "Not found.",
                "type": "invalid_request",
            },
        )

    def test_cannot_update_plans(self):
        plan = self.create_plan()

        # PUT UPDATE
        response = self.client.put(f"/plans/{plan.key}", {"price_id": "new_pricing"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        plan.refresh_from_db()
        self.assertNotEqual(plan.price_id, "new_pricing")

        # PATCH UPDATE
        response = self.client.patch(f"/plans/{plan.key}", {"price_id": "new_pricing"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        plan.refresh_from_db()
        self.assertNotEqual(plan.price_id, "new_pricing")
