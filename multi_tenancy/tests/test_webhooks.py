import datetime
from unittest.mock import MagicMock, patch

import pytz
import vcr
from django.test import Client
from django.utils import timezone
from freezegun.api import freeze_time
from multi_tenancy.models import OrganizationBilling, Plan
from multi_tenancy.stripe import compute_webhook_signature
from posthog.api.test.base import TransactionBaseTest
from posthog.models import User
from rest_framework import status

from .base import PlanTestMixin


class StripeWebhookTestMixin(TransactionBaseTest, PlanTestMixin):
    def generate_webhook_signature(self, payload: str, secret: str, timestamp: timezone.datetime = None,) -> str:
        timestamp = timezone.now() if not timestamp else timestamp
        computed_timestamp: int = int(timestamp.timestamp())
        signature: str = compute_webhook_signature(
            "%d.%s" % (computed_timestamp, payload), secret,
        )
        return f"t={computed_timestamp},v1={signature}"


class TestPaymentSucceededWebhooks(StripeWebhookTestMixin):
    @patch("posthoganalytics.capture")
    @vcr.use_cassette(cassette_library_dir="multi_tenancy/tests/cassettes", filter_headers=["authorization"])
    def test_initial_billing_period_set_from_webhook(self, mock_capture):
        """
        Tests initial subscription update (same behavior for flat & metered-based subscriptions).
        """

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"
        plan = Plan.objects.create(key="metered_plan", name="Test Plan", price_id="price_test", is_metered_billing=True)

        organization, _, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, plan=plan, stripe_customer_id="cus_pxHcmaEDNOq"
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
                    "customer": "cus_pxHcmaEDNOq",
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
                    "subscription": "sub_J2hjz4fq3oeYZj"
                }
            },
            "livemode": false,
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(enforce_csrf_checks=True)  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):
            response = csrf_client.post(
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        billing_period_ends = timezone.datetime(
            2021, 4, 2, 17, 47, 25, tzinfo=pytz.UTC,
        )  # note this date comes from Stripe (cassette fixture in this case), not from the webhook
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, billing_period_ends)
        self.assertEqual(instance.stripe_subscription_id, "sub_J2hjz4fq3oeYZj")  # ID is saved too

        # Assert that analytics event is fired
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "billing subscription activated",
            {
                "plan_key": "metered_plan",
                "billing_period_ends": billing_period_ends,
                "organization_id": str(organization.id),
            },
        )

    @patch("posthoganalytics.capture")
    @vcr.use_cassette(cassette_library_dir="multi_tenancy/tests/cassettes", filter_headers=["authorization"])
    def test_billing_period_is_updated_when_webhook_is_received(self, mock_capture):
        """
        When we receive invoice.payment_succeeded webhook, we update the subscription period end.
        Tests regular ongoing subscription updates (same behavior for flat & metered-based subscriptions).
        """

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"
        plan = Plan.objects.create(key="test_plan", name="Test Plan", price_id="price_test")

        organization, _, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_aEDNOHbSpxHcmq",
            plan=plan,
            billing_period_ends=datetime.datetime(2020, 3, 1, 23, 59, 59, 59, tzinfo=pytz.UTC),
            stripe_subscription_id="sub_J2hjz4fq3oeYZj",
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
                    "subscription": "sub_J2hjz4fq3oeYZj"
                }
            },
            "livemode": false,
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(enforce_csrf_checks=True)  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):
            response = csrf_client.post(
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        billing_period_ends = timezone.datetime(
            2021, 4, 2, 17, 47, 25, tzinfo=pytz.UTC,
        )  # note this date comes from Stripe (cassette fixture in this case), not from the webhook
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, billing_period_ends)

        # Assert that analytics event is fired
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "billing subscription paid",
            {
                "plan_key": "test_plan",
                "billing_period_ends": billing_period_ends,
                "organization_id": str(organization.id),
            },
        )

    @patch("posthoganalytics.capture")
    @patch("multi_tenancy.tasks.capture_message")
    @patch("multi_tenancy.tasks.update_subscription_billing_period.retry")
    @vcr.use_cassette(cassette_library_dir="multi_tenancy/tests/cassettes", filter_headers=["authorization"])
    def test_billing_period_not_updated_if_subscription_is_overdue(self, mock_retry, mock_sentry_message, mock_capture):
        """
        Tests the edge case (in general should never happen) when we receive invoice.payment_succeeded but the
        subscription is overdue or cancelled on Stripe.
        """

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"
        plan = Plan.objects.create(key="flat", name="Flat Plan", price_id="price_test")

        organization, _, user = self.create_org_team_user()
        current_period_end = datetime.datetime(2020, 3, 1, 23, 59, 59, 59, tzinfo=pytz.UTC)
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            stripe_customer_id="cus_IuiYICjeetKPlE",
            plan=plan,
            billing_period_ends=current_period_end,
            stripe_subscription_id="sub_J2iADLADfn3jSA",
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
                    "customer": "cus_IuiYICjeetKPlE",
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
                    "subscription": "sub_J2iADLADfn3jSA"
                }
            },
            "livemode": false,
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(enforce_csrf_checks=True)  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):
            response = csrf_client.post(
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, current_period_end)  # billing period is not updated

        # Task is scheduled for retry
        mock_retry.assert_called()

        # Error reported to Sentry
        mock_sentry_message.assert_called_once_with(
            "Received update_subscription_billing_period but subscription is not active (sub_J2iADLADfn3jSA)."
        )

        # No event is reported as nothing was updated
        mock_capture.assert_not_called()

    @patch("posthoganalytics.capture")
    @patch("multi_tenancy.views.capture_message")
    def test_billing_period_not_updated_if_subscription_doesnt_match(self, mock_sentry_message, mock_capture):
        """
        Tests the edge case (in general should never happen) when we receive invoice.payment_succeeded but the
        subscription does not match records on file.
        """

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"
        plan = Plan.objects.create(key="flat", name="Flat Plan", price_id="price_test")

        organization, _, user = self.create_org_team_user()
        current_period_end = datetime.datetime(2020, 3, 1, 23, 59, 59, 59, tzinfo=pytz.UTC)
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            stripe_customer_id="cus_IuiYICjeetKPlE",
            plan=plan,
            billing_period_ends=current_period_end,
            stripe_subscription_id="sub_J2iADLADfn3jSA",
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
                    "customer": "cus_IuiYICjeetKPlE",
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
                    "subscription": "sub_not_a_match"
                }
            },
            "livemode": false,
            "pending_webhooks": 1,
            "type": "invoice.payment_succeeded"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(enforce_csrf_checks=True)  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):
            response = csrf_client.post(
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, current_period_end)  # billing period is not updated

        # Error reported to Sentry
        mock_sentry_message.assert_called_once()

        # No event is reported as nothing was updated
        mock_capture.assert_not_called()


class TestSpecialWebhookHandling(StripeWebhookTestMixin):
    @patch("posthoganalytics.capture")
    @patch("multi_tenancy.views.cancel_payment_intent")
    @vcr.use_cassette(cassette_library_dir="multi_tenancy/tests/cassettes", filter_headers=["authorization"])
    def test_billing_period_special_handling_for_startup_plan(
        self, cancel_payment_intent, mock_capture,
    ):

        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        organization, _, user1 = self.create_org_team_user()
        user2 = User.objects.create_user(email="test_user_2@posthog.com", first_name="Test 2", password="12345678")
        user2.join(organization=organization)
        startup_plan = Plan.objects.create(key="startup", name="Startup", price_id="not_set")
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization,
            should_setup_billing=True,
            stripe_customer_id="cus_IuiXChYGDqmHPi",
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
                    "customer":"cus_IuiXChYGDqmHPi",
                    "on_behalf_of":null,
                    "payment_method": "card_1IRjpiEuIatRXSdzMcSSmCU9"
                }
            },
            "livemode":false,
            "pending_webhooks":1,
            "type":"payment_intent.amount_capturable_updated"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(enforce_csrf_checks=True)  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret):

            response = csrf_client.post(
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that the period end was updated (1 year from now)
        instance.refresh_from_db()
        self.assertTrue(
            (timezone.now() + datetime.timedelta(days=365) - instance.billing_period_ends).total_seconds(), 2,
        )
        self.assertEqual(
            instance.stripe_subscription_item_id, ""
        )  # this is not updated as there's no Stripe subscription on startup plan

        # Check that the payment is cancelled (i.e. not captured)
        cancel_payment_intent.assert_called_once_with("pi_TxLb1HS1CyhnDR")

        # Assert that special analytics event is fired; test it's sent for every user in the org too
        self.assertEqual(mock_capture.call_count, 2)
        for _user in [user2, user1]:
            mock_capture.assert_any_call(
                _user.distinct_id,
                "billing card validated",
                {
                    "plan_key": "startup",
                    "billing_period_ends": instance.billing_period_ends,
                    "organization_id": str(organization.id),
                },
            )

    @freeze_time("2020-11-09T14:59:30Z")
    @patch("posthoganalytics.capture")
    @patch("multi_tenancy.stripe._get_customer_id")
    @patch("multi_tenancy.stripe.stripe.Subscription.create")
    @patch("multi_tenancy.views.cancel_payment_intent")
    @patch("stripe.Customer.modify")
    def test_handle_webhook_for_metered_plans_after_card_registration(
        self, set_default_pm, cancel_payment_intent, mock_session_create, mock_customer_id, mock_capture,
    ):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"
        mock_customer_id.return_value = "cus_MeteredI2MVxJI"
        mock_session_data = MagicMock()
        mock_session_data.to_dict.return_value = {"items": {"data": [{"id": "si_1a2b3c4d", "metadata": {"a": "b"}}]}}

        mock_session_create.return_value = mock_session_data

        organization, _, user = self.create_org_team_user()
        plan = Plan.objects.create(
            key="metered", name="Metered Plan", price_id="price_zyxwvu", is_metered_billing=True,
        )

        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, stripe_customer_id="cus_MeteredI2MVxJI", plan=plan,
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
                    "customer":"cus_MeteredI2MVxJI",
                    "on_behalf_of":null,
                    "payment_method": "pm_iEuIaI2h3ETxMVtRXS"
                }
            },
            "livemode":false,
            "pending_webhooks":1,
            "type":"payment_intent.amount_capturable_updated"
        }
        """

        signature: str = self.generate_webhook_signature(body, sample_webhook_secret)
        csrf_client = Client(enforce_csrf_checks=True,)  # Custom client to ensure CSRF checks pass

        with self.settings(STRIPE_WEBHOOK_SECRET=sample_webhook_secret, BILLING_TRIAL_DAYS=30):

            response = csrf_client.post(
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert that Stripe was called with the correct data
        mock_session_create.assert_called_once_with(
            customer="cus_MeteredI2MVxJI",
            items=[{"price": "price_zyxwvu"}],
            trial_period_days=30,
            billing_cycle_anchor=datetime.datetime(2021, 1, 1, 23, 59, 59, 999999, tzinfo=pytz.UTC,),
        )

        # Check that the instance is correctly updated
        instance.refresh_from_db()
        self.assertEqual(instance.billing_period_ends, None)  # this is not changed
        self.assertEqual(
            instance.stripe_subscription_item_id, "si_1a2b3c4d",
        )  # subscription ID is updated after subscription is created

        # Check that the payment is cancelled (i.e. not captured)
        cancel_payment_intent.assert_called_once_with("pi_TxLb1HS1CyhnDR")

        # Assert that special analytics event is fired
        mock_capture.assert_called_with(
            user.distinct_id,
            "billing card validated",
            {"plan_key": "metered", "billing_period_ends": None, "organization_id": str(organization.id)},
        )

        set_default_pm.assert_called_once_with(
            "cus_MeteredI2MVxJI", invoice_settings={"default_payment_method": "pm_iEuIaI2h3ETxMVtRXS"}
        )

    @patch("multi_tenancy.views.capture_exception")
    def test_webhook_with_invalid_signature_fails(self, capture_exception):
        sample_webhook_secret: str = "wh_sec_test_abcdefghijklmnopqrstuvwxyz"

        organization, team, user = self.create_org_team_user()
        instance: OrganizationBilling = OrganizationBilling.objects.create(
            organization=organization, should_setup_billing=True, stripe_customer_id="cus_bEDNOHbSpxHcmq",
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
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
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
            organization=organization, should_setup_billing=True, stripe_customer_id="cus_dEDNOHbSpxHcmq",
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
                "/billing/stripe_webhook", body, content_type="text/plain", HTTP_STRIPE_SIGNATURE=signature,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        capture_message.assert_called_once_with(
            "Received invoice.payment_succeeded for cus_12345678 but customer is not in the database.",
        )
