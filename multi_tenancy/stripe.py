import datetime
import logging
from typing import Dict, Optional, Tuple, Union

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

import stripe
from multi_tenancy.utils import get_billing_cycle_anchor

logger = logging.getLogger(__name__)


def _init_stripe() -> None:
    if not settings.STRIPE_API_KEY:
        raise ImproperlyConfigured(
            "Cannot process billing because env vars are not properly set.",
        )

    stripe.api_key = settings.STRIPE_API_KEY


def _get_customer_id(customer_id: str, email: str = "") -> str:
    _init_stripe()
    if customer_id:
        return customer_id
    return stripe.Customer.create(email=email).id


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

    if settings.TEST:
        logger.info(f"Simulating Stripe checkout session: {payload}")
        return ("cs_1234567890", customer_id)

    session = stripe.checkout.Session.create(**payload)

    return (session.id, customer_id)


def create_zero_auth(
    email: str, base_url: str, customer_id: str = "",
) -> Tuple[str, str]:

    customer_id = _get_customer_id(customer_id, email)

    payload: Dict = {
        "payment_method_types": ["card"],
        "line_items": [
            {
                "amount": 50,
                "quantity": 1,
                "currency": "USD",
                "name": "Card authorization",
            },
        ],
        "mode": "payment",
        "payment_intent_data": {
            "capture_method": "manual",
            "statement_descriptor": "POSTHOG PREAUTH",
        },
        "customer": customer_id,
        "success_url": base_url + "billing/welcome?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": base_url + "billing/failed?session_id={CHECKOUT_SESSION_ID}",
    }

    session = stripe.checkout.Session.create(**payload)

    return (session.id, customer_id)


def create_subscription(price_id: str = "", customer_id: str = "",) -> Tuple[str, str]:
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

    return (subscription_data["items"]["data"][0]["id"], customer_id)


def cancel_payment_intent(payment_intent_id: str) -> None:
    _init_stripe()
    stripe.PaymentIntent.cancel(payment_intent_id)


def customer_portal_url(customer_id: str) -> Optional[str]:
    _init_stripe()

    if settings.TEST:
        return f"/manage-my-billing/{customer_id}"

    return stripe.billing_portal.Session.create(customer=customer_id).url


def parse_webhook(payload: Union[bytes, str], signature: str) -> Dict:

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise ImproperlyConfigured(
            "Cannot process billing webhook because env vars are not properly set.",
        )

    return stripe.Webhook.construct_event(
        payload, signature, settings.STRIPE_WEBHOOK_SECRET,
    )


def compute_webhook_signature(payload: str, secret: str) -> str:
    return stripe.webhook.WebhookSignature._compute_signature(payload, secret)


def report_subscription_item_usage(
    subscription_item_id: str, billed_usage: int, timestamp: datetime.datetime,
) -> bool:
    _init_stripe()

    # The idempotency_key is the combination of the subscription ID and current timestamp, as we should only report
    # usage once per day, this should ensure no events are doubled counted
    usage_record = stripe.SubscriptionItem.create_usage_record(
        subscription_item_id,
        quantity=billed_usage,
        timestamp=timezone.now(),
        idempotency_key=f"{subscription_item_id}-{timestamp.strftime('%Y-%m-%d')}",
    )
    return bool(usage_record.id)
