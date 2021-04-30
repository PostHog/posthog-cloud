import datetime
import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple, Union

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from sentry_sdk.api import capture_exception

import stripe
from multi_tenancy.utils import get_billing_cycle_anchor

logger = logging.getLogger(__name__)


def _init_stripe() -> None:
    if not settings.STRIPE_API_KEY:
        raise ImproperlyConfigured("Cannot process billing because env vars are not properly set.")

    stripe.api_key = settings.STRIPE_API_KEY


def _get_customer_id(customer_id: str, email: str = "") -> str:
    _init_stripe()
    if customer_id:
        return customer_id
    return stripe.Customer.create(email=email).id


def set_default_payment_method_for_customer(customer_id: str, payment_method_id: str) -> bool:
    _init_stripe()
    return (
        stripe.Customer.modify(
            customer_id, invoice_settings={"default_payment_method": payment_method_id}
        ).invoice_settings.default_payment_method
        == payment_method_id
    )


def create_subscription_checkout_session(
    email: str, base_url: str, price_id: str = "", customer_id: str = "",
) -> Tuple[str, str]:
    """
    Creates a checkout session for a billing subscription (used by flat-fee recurring subscriptions)
    """

    customer_id = _get_customer_id(customer_id, email)

    payload: Dict = {
        "payment_method_types": ["card"],
        "line_items": [{"price": price_id, "quantity": 1}],
        "mode": "subscription",
        "customer": customer_id,
        "success_url": base_url + "billing/welcome?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": base_url + "billing/failed?session_id={CHECKOUT_SESSION_ID}",
    }

    # TODO: We shouldn't do special handling for when running tests, use VCR.py to use test fixtures
    if settings.TEST:
        logger.info(f"Simulating Stripe checkout session: {payload}")
        return ("cs_1234567890", customer_id)

    session = stripe.checkout.Session.create(**payload)

    return (session.id, customer_id)


def create_zero_auth(email: str, base_url: str, customer_id: str = "") -> Tuple[str, str]:

    customer_id = _get_customer_id(customer_id, email)

    payload: Dict = {
        "payment_method_types": ["card"],
        "line_items": [{"amount": 50, "quantity": 1, "currency": "USD", "name": "Card authorization"}],
        "mode": "payment",
        "payment_intent_data": {
            "capture_method": "manual",
            "statement_descriptor": "POSTHOG PREAUTH",
            "setup_future_usage": "off_session",
        },
        "customer": customer_id,
        "success_url": base_url + "billing/welcome?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": base_url + "billing/failed?session_id={CHECKOUT_SESSION_ID}",
    }

    session = stripe.checkout.Session.create(**payload)

    return (session.id, customer_id)


def create_subscription(price_id: str = "", customer_id: str = "",) -> Dict[str, str]:
    """
    Creates a subscription for an existing customer with payment details already set up. Used mainly for metered
    plans.
    """

    customer_id = _get_customer_id(
        customer_id
    )  # we don't pass the email because the customer is always created before (on zero auth)

    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
        trial_period_days=settings.BILLING_TRIAL_DAYS,
        billing_cycle_anchor=get_billing_cycle_anchor(timezone.now()),
    )

    subscription_data = subscription.to_dict()

    return {
        "subscription_id": subscription_data["id"],
        "subscription_item_id": subscription_data["items"]["data"][0]["id"],  # TODO: DEPRECATED
        "customer_id": customer_id,
    }


def cancel_payment_intent(payment_intent_id: str) -> None:
    _init_stripe()
    stripe.PaymentIntent.cancel(payment_intent_id)


def customer_portal_url(customer_id: str) -> Optional[str]:
    _init_stripe()

    # TODO: We shouldn't do special handling for when running tests, use VCR.py to use test fixtures
    if settings.TEST:
        return f"/manage-my-billing/{customer_id}"

    return stripe.billing_portal.Session.create(customer=customer_id).url


def parse_webhook(payload: Union[bytes, str], signature: str) -> Dict:

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise ImproperlyConfigured("Cannot process billing webhook because env vars are not properly set.",)

    return stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET,)


def compute_webhook_signature(payload: str, secret: str) -> str:
    return stripe.webhook.WebhookSignature._compute_signature(payload, secret)


def report_subscription_item_usage(subscription_id: str, billed_usage: int, timestamp: datetime.datetime,) -> bool:
    _init_stripe()

    subscription = get_subscription(subscription_id)
    subscription_items = subscription.get("items", {}).get("data", [])
    subscription_item_id = None
    for item in subscription_items:
        # if we have multiple items in a subscription, pick one that is metered usage.
        if subscription_item_id is None or item.get("price").get("recurring").get("usage_type") == "metered":
            subscription_item_id = item.get("id")

    # The idempotency_key is the combination of the subscription ID and current timestamp, as we should only report
    # usage once per day, this should ensure no events are doubled counted
    usage_record = stripe.SubscriptionItem.create_usage_record(
        subscription_item_id,
        quantity=billed_usage,
        timestamp=timezone.now(),
        idempotency_key=f"{subscription_item_id}-{timestamp.strftime('%Y-%m-%d')}",
    )
    return bool(usage_record.id)


def get_subscription(subscription_id: str) -> Dict[str, Any]:
    _init_stripe()
    return stripe.Subscription.retrieve(subscription_id)


def get_current_usage_bill(subscription_id: str) -> Optional[Decimal]:
    """
    Obtains the upcoming invoice (not billed yet) for the relevant subscription and parses the
    zero-decimal amount.
    """
    _init_stripe()

    try:
        invoice = stripe.Invoice.upcoming(subscription=subscription_id)
        return Decimal(invoice["amount_due"] / 100) if invoice.get("amount_due") else None
    except Exception as e:
        capture_exception(e)
        return None
