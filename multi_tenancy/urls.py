from typing import List

from django.contrib.auth import decorators
from django.urls import path, re_path

from posthog.urls import home
from posthog.urls import urlpatterns as posthog_urls

from .views import (MultiTenancyTeamSignupViewset, billing_failed_view,
                    billing_hosted_view, billing_welcome_view,
                    stripe_billing_portal, stripe_checkout_view,
                    stripe_webhook, user_with_billing)

# Include `posthog-production` override routes first
urlpatterns: List = [
    path("api/user", user_with_billing,),
    path(
        "api/user/", user_with_billing,
    ),  # Override to include billing information (included at the top to overwrite main repo `posthog` route)
    path("api/team/signup", MultiTenancyTeamSignupViewset.as_view()),
    path(
        "api/team/signup/", MultiTenancyTeamSignupViewset.as_view()
    ),  # Override to support setting a billing plan on signup
]

# Include `posthog` default routes, except the home route (to give precendence to billing routes)
urlpatterns += posthog_urls[:-1]


# Include `posthog-production` routes and the home route as fallback
urlpatterns += [
    path("billing/setup", stripe_checkout_view, name="billing_setup",),
    path(
        "billing/setup/", stripe_checkout_view, name="billing_setup",
    ),  # Redirect to Stripe Checkout to set-up billing (requires session ID)
    path("billing/manage", stripe_billing_portal, name="billing_manage",),
    path(
        "billing/manage/", stripe_billing_portal, name="billing_manage",
    ),  # Redirect to Stripe Customer Portal to manage subscription
    path("billing/welcome", billing_welcome_view, name="billing_welcome",),
    path(
        "billing/welcome/", billing_welcome_view, name="billing_welcome",
    ),  # Page with success message after setting up billing
    path("billing/failed", billing_failed_view, name="billing_failed",),
    path(
        "billing/failed/", billing_failed_view, name="billing_failed",
    ),  # Page with failure message after attempting to set up billing
    path("billing/hosted", billing_hosted_view, name="billing_hosted",),
    path(
        "billing/hosted/", billing_hosted_view, name="billing_hosted",
    ),  # Page with success message after setting up billing for hosted plans
    path(
        "billing/stripe_webhook",
        stripe_webhook,
        name="billing_stripe_webhook",
    ), # Stripe Webhook
    re_path(
        r"^.*", decorators.login_required(home),
    ),  # Should always be at the very last position
]
