from typing import List
from posthog.urls import urlpatterns as posthog_urls, home
from django.urls import path, re_path
from django.contrib.auth import decorators
from multi_tenancy.views import (
    signup_view,
    user_with_billing,
    stripe_checkout_view,
    stripe_billing_portal,
    billing_welcome_view,
    billing_failed_view,
    billing_hosted_view,
    stripe_webhook,
)

# Include `posthog-production` override routes first
urlpatterns: List = [
    path(
        "api/user/", user_with_billing
    ),  # Override to include billing information (included at the top to overwrite main repo `posthog` route)
    path("signup", signup_view, name="signup"), # TODO: Temp to prevent breaking app.posthog.com with https://github.com/PostHog/posthog/pull/1535
]

# Include `posthog` default routes, except the home route (to give precendence to billing routes)
urlpatterns += posthog_urls[:-1]

# Include `posthog-production` routes and the home route as fallback
urlpatterns += [
    path(
        "billing/setup", stripe_checkout_view, name="billing_setup"
    ),  # Redirect to Stripe Checkout to set-up billing (requires session ID)
    path(
        "billing/manage", stripe_billing_portal, name="billing_manage"
    ),  # Redirect to Stripe Customer Portal to manage subscription
    path(
        "billing/welcome", billing_welcome_view, name="billing_welcome"
    ),  # Page with success message after setting up billing
    path(
        "billing/failed", billing_failed_view, name="billing_failed"
    ),  # Page with failure message after attempting to set up billing
    path(
        "billing/hosted", billing_hosted_view, name="billing_hosted"
    ),  # Page with success message after setting up billing for hosted plans
    path(
        "billing/stripe_webhook", stripe_webhook, name="billing_stripe_webhook"
    ),  # Stripe Webhook
    re_path(r"^.*", decorators.login_required(home)), # Should always be at the very last position
]
