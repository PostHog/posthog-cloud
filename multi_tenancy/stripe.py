import logging
from typing import Dict, Tuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import stripe

logger = logging.getLogger(__name__)


def create_subscription(
    email: str, customer_id: str = "", custom_price_id: str = "",
) -> Tuple[str, str]:

    if not settings.STRIPE_API_KEY or not settings.STRIPE_DEFAULT_PRICE_ID:
        logger.warning(
            "Cannot process billing setup because env vars are not properly set.",
        )
        return (None, None)

    stripe.api_key = settings.STRIPE_API_KEY

    # Create the customer first if it doesn't exist
    if not customer_id:
        customer_id = (
            stripe.Customer.create(email=email).id
            if not settings.TEST
            else "cus_000111222"
        )

    payload: Dict = {
        "payment_method_types": ["card"],
        "line_items": [
            {
                "price": custom_price_id or settings.STRIPE_DEFAULT_PRICE_ID,
                "quantity": 1,
            }
        ],
        "mode": "subscription",
        "customer": customer_id,
        "success_url": settings.SITE_URL
        + "/billing/welcome?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": settings.SITE_URL
        + "/billing/failed?session_id={CHECKOUT_SESSION_ID}",
    }

    if settings.TEST:
        logger.info(f"Simulating Stripe checkout session: {payload}")
        return ("cs_1234567890", customer_id)

    session = stripe.checkout.Session.create(**payload)

    return (session.id, customer_id)


def customer_portal_url(customer_id: str) -> str:

    if not settings.STRIPE_API_KEY:
        logger.warning(
            "Cannot process billing management because env vars are not properly set."
        )
        return None

    if settings.TEST:
        return f"/manage-my-billing/{customer_id}"

    stripe.api_key = settings.STRIPE_API_KEY

    session = stripe.billing_portal.Session.create(customer=customer_id,)

    return session.url


def parse_webhook(payload: str, signature: str) -> Dict:

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error(
            "Cannot process Stripe webhook because env vars are not properly set."
        )
        return None

    event = None
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.info(f"Error parsing webhook, unexpected payload. Ignoring. {payload}",)
        return None
    except stripe.error.SignatureVerificationError:
        logger.warning(
            f"Ignoring webhook because signature ({signature}) did not match. {payload}",
        )
        return None
    return event


def compute_webhook_signature(payload: str, secret: str) -> str:
    return stripe.webhook.WebhookSignature._compute_signature(payload, secret)
