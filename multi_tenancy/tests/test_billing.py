import datetime
import random
from typing import Dict
from unittest.mock import MagicMock, patch

import pytz
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from rest_framework import status

from multi_tenancy.models import Plan, TeamBilling
from multi_tenancy.stripe import compute_webhook_signature
from posthog.api.test.base import BaseTest, TransactionBaseTest
from posthog.models import Team, User


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


class TestTeamBilling(TransactionBaseTest):

    TESTS_API = True

    def create_team_and_user(self):
        team: Team = Team.objects.create(api_token="token123")
        user = User.objects.create_user(
            f"user{random.randint(100, 999)}@posthog.com", password=self.TESTS_PASSWORD,
        )
        team.users.add(user)
        team.save()
        return (team, user)

    def create_plan(self, **kwargs):
        return Plan.objects.create(
            **{
                "key": f"plan_{random.randint(100000, 999999)}",
                "price_id": f"price_{random.randint(1000000, 9999999)}",
                "name": "Test Plan",
                **kwargs,
            },
        )

    # Setting up billing

    def test_team_should_not_set_up_billing_by_default(self):

        count: int = TeamBilling.objects.count()
        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertNotIn(
            "billing", response_data,
        )  # key should not be present if plan = `None`

        # TeamBilling object should've been created if non-existent
        self.assertEqual(TeamBilling.objects.count(), count + 1)
        team_billing: TeamBilling = TeamBilling.objects.get(team=self.team)

        # Test default values for TeamBilling
        self.assertEqual(team_billing.should_setup_billing, False)
        self.assertEqual(team_billing.stripe_customer_id, "")
        self.assertEqual(team_billing.stripe_checkout_session, "")

    def test_team_that_should_not_set_up_billing(self):
        team, user = self.create_team_and_user()
        TeamBilling.objects.create(team=team, should_setup_billing=False)
        self.client.force_login(user)

        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertNotIn(
            "billing", response_data,
        )  # key should not be present if plan = `None`

    @patch("multi_tenancy.stripe._get_customer_id")
    def test_team_that_should_set_up_billing_starts_a_checkout_session(
        self, mock_customer_id,
    ):
        mock_customer_id.return_value = "cus_000111222"
        team, user = self.create_team_and_user()
        plan = self.create_plan(custom_setup_billing_message="Sign up now!")
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True, plan=plan,
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
        Startup handled is handled with custom logic, because only a validation charge is made
        instead of setting up a full subscription.
        """

        mock_customer_id.return_value = "cus_000111222"
        mock_cs_session = MagicMock()
        mock_cs_session.id = "cs_1234567890"

        mock_checkout.return_value = mock_cs_session
        team, user = self.create_team_and_user()
        plan = self.create_plan(key="startup")
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True, plan=plan,
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
            {"key": "startup", "name": plan.name, "custom_setup_billing_message": "",},
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session, "cs_1234567890",
        )
        self.assertEqual(instance.stripe_customer_id, "cus_000111222")

    def test_cannot_start_double_billing_subscription(self):
        team, user = self.create_team_and_user()
        plan = self.create_plan()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team,
            should_setup_billing=True,
            plan=plan,
            billing_period_ends=timezone.now()
            + datetime.timedelta(minutes=random.randint(10, 99)),
        )
        self.client.force_login(user)

        # Make sure the billing is already active
        self.assertEqual(instance.is_billing_active, True)

        response_data = self.client.post("/api/user/").json()

        self.assertEqual(
            response_data["billing"],
            {
                "plan": {
                    "key": plan.key,
                    "name": plan.name,
                    "custom_setup_billing_message": "",
                },
            },
        )

    def test_silent_fail_if_stripe_variables_are_not_properly_configured(self):
        """
        If Stripe variables are not properly set, an exception will be sent to Sentry.
        """

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True, plan=self.create_plan(),
        )
        self.client.force_login(user)

        with self.settings(STRIPE_API_KEY=""):
            response_data: Dict = self.client.post("/api/user/").json()

        self.assertNotIn(
            "should_setup_billing", response_data["billing"],
        )

        instance.refresh_from_db()
        self.assertEqual(instance.stripe_checkout_session, "")

    # Manage billing

    def test_user_can_manage_billing(self):

        team, user = self.create_team_and_user()
        TeamBilling.objects.create(
            team=team, should_setup_billing=True, stripe_customer_id="cus_12345678",
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

        team, user = self.create_team_and_user()
        TeamBilling.objects.create(
            team=team, should_setup_billing=True,
        )
        self.client.force_login(user)

        response = self.client.post("/billing/manage")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, "/")

    # Stripe webhooks

    def generate_webhook_signature(
        self, payload: str, secret: str, timestamp: datetime.datetime = None,
    ) -> str:
        timestamp = timezone.now() if not timestamp else timestamp
        computed_timestamp: int = int(timestamp.timestamp())
        signature: str = compute_webhook_signature(
            "%d.%s" % (computed_timestamp, payload), secret,
        )
        return f"t={computed_timestamp},v1={signature}"

    def test_billing_period_is_updated_when_webhook_is_received(self):

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team,
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
            datetime.datetime(2020, 8, 7, 12, 28, 15, tzinfo=pytz.UTC),
        )

    @patch("multi_tenancy.views.capture_exception")
    def test_webhook_with_invalid_signature_fails(self, capture_exception):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team,
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

        # Check that the period end & price ID was NOT updated
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, None)
        self.assertEqual(instance.price_id, "")

    def test_webhook_with_invalid_payload_fails(self):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team,
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
                invalid_payload, sample_webhook_secret
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

    def test_webhook_where_customer_cannot_be_located_is_logged(self):
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

            with self.assertLogs(logger="multi_tenancy.views") as l:
                response = self.client.post(
                    "/billing/stripe_webhook",
                    body,
                    content_type="text/plain",
                    HTTP_STRIPE_SIGNATURE=signature,
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn(
                    "Received invoice.payment_succeeded for cus_12345678 but customer is not in the database.",
                    l.output[0],
                )
