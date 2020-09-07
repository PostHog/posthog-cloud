import datetime
import random
from typing import Dict

import pytz
from django.conf import settings
from django.utils import timezone
from rest_framework import status

from multi_tenancy.models import Plan, TeamBilling
from multi_tenancy.stripe import compute_webhook_signature
from posthog.api.test.base import TransactionBaseTest
from posthog.models import Team, User


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

    # Setting up billing

    def test_team_should_not_set_up_billing_by_default(self):

        count: int = TeamBilling.objects.count()
        response = self.client.post("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()
        self.assertNotIn(
            "billing", response_data,
        )  # key should not be present if should_setup_billing = `False`

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
        )  # key should not be present if should_setup_billing = `False`

    def test_team_that_should_set_up_billing_gets_an_started_checkout_session(self):

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True,
        )
        self.client.force_login(user)

        with self.assertLogs("multi_tenancy.stripe") as l:

            response = self.client.post("/api/user/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertIn(
                "cus_000111222", l.output[0],
            )  # customer ID is included in the payload to Stripe

            self.assertIn(
                settings.STRIPE_DEFAULT_PRICE_ID, l.output[0],
            )  # Default price is used

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_1234567890",
        )
        self.assertEqual(
            response_data["billing"]["subscription_url"],
            "/billing/setup?session_id=cs_1234567890",
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session,
            response_data["billing"]["stripe_checkout_session"],
        )
        self.assertEqual(instance.stripe_customer_id, "cus_000111222")

    def test_team_with_custom_pricing(self):
        """
        Team has a `custom_price_id` and therefore is billed differently.
        """

        plan = Plan.objects.create(key="growth", price_id="price_custom_123")
        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True, plan=plan,
        )
        self.client.force_login(user)

        with self.assertLogs("multi_tenancy.stripe") as l:

            response = self.client.post("/api/user/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertIn(
                "price_custom_123", l.output[0],
            )  # Custom price ID is used

        response_data: Dict = response.json()
        self.assertEqual(response_data["billing"]["should_setup_billing"], True)
        self.assertEqual(
            response_data["billing"]["stripe_checkout_session"], "cs_1234567890",
        )
        self.assertEqual(
            response_data["billing"]["subscription_url"],
            "/billing/setup?session_id=cs_1234567890",
        )

        # Check that the checkout session was saved to the database
        instance.refresh_from_db()
        self.assertEqual(
            instance.stripe_checkout_session,
            response_data["billing"]["stripe_checkout_session"],
        )
        self.assertEqual(instance.stripe_customer_id, "cus_000111222")

    def test_cannot_start_double_billing_subscription(self):
        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team,
            should_setup_billing=True,
            billing_period_ends=timezone.now()
            + datetime.timedelta(minutes=random.randint(10, 99)),
        )
        self.client.force_login(user)

        # Make sure the billing is already active
        self.assertEqual(instance.is_billing_active, True)

        response_data = self.client.post("/api/user/").json()
        self.assertNotIn("billing", response_data)

    def test_warning_is_logged_if_stripe_variables_are_not_properly_configured(self):

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True
        )
        self.client.force_login(user)

        with self.settings(STRIPE_DEFAULT_PRICE_ID=""):

            with self.assertLogs("multi_tenancy.stripe") as l:
                response_data: Dict = self.client.post("/api/user/").json()
                self.assertEqual(
                    l.output[0],
                    "WARNING:multi_tenancy.stripe:Cannot process billing setup because env vars are not properly set.",
                )

            self.assertNotIn(
                "billing", response_data
            )  # even if `should_setup_billing=True`
            instance.refresh_from_db()
            self.assertEqual(instance.stripe_checkout_session, "")

        with self.settings(STRIPE_API_KEY=""):

            with self.assertLogs("multi_tenancy.stripe") as l:
                response_data: Dict = self.client.post("/api/user/").json()
                self.assertEqual(
                    l.output[0],
                    "WARNING:multi_tenancy.stripe:Cannot process billing setup because env vars are not properly set.",
                )

            self.assertNotIn(
                "billing", response_data
            )  # even if `should_setup_billing=True`
            instance.refresh_from_db()
            self.assertEqual(instance.stripe_checkout_session, "")

    # Manage billing

    def test_user_can_manage_billing(self):

        team, user = self.create_team_and_user()
        instance: TeamBilling = TeamBilling.objects.create(
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
        instance: TeamBilling = TeamBilling.objects.create(
            team=team, should_setup_billing=True
        )
        self.client.force_login(user)

        response = self.client.post("/billing/manage")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, "/")

    # Stripe webhooks

    def generate_webhook_signature(
        self, payload: str, secret: str, timestamp: datetime.datetime = timezone.now()
    ) -> str:
        timestamp: int = int(timestamp.timestamp())
        signature: str = compute_webhook_signature(
            "%d.%s" % (timestamp, payload), secret
        )
        return f"t={timestamp},v1={signature}"

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

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):

            response = self.client.post(
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

    def test_webhook_with_invalid_signature_fails(self):
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

            with self.assertLogs(logger="multi_tenancy.stripe") as l:
                response = self.client.post(
                    "/billing/stripe_webhook",
                    body,
                    content_type="text/plain",
                    HTTP_STRIPE_SIGNATURE=signature,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("Ignoring webhook because signature", l.output[0])

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
