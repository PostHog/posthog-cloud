from typing import List

from django.urls import path
from posthog.urls import opt_slash_path
from posthog.urls import urlpatterns as posthog_urls

from .views import (
    BillingSubscribeViewset,
    BillingViewset,
    MultiTenancyOrgSignupViewset,
    PlanViewset,
    billing_failed_view,
    billing_hosted_view,
    billing_welcome_view,
    plan_template,
    stripe_billing_portal,
    stripe_checkout_view,
    stripe_webhook,
)

# Include `posthog-cloud` routes first
urlpatterns: List = [
    opt_slash_path(
        "api/signup", MultiTenancyOrgSignupViewset.as_view(),
    ),  # Override to support setting a billing plan on signup
    opt_slash_path("api/plans", PlanViewset.as_view({"get": "list"}), name="billing_plans"),
    path("api/plans/<str:key>/template/", plan_template, name="billing_plan_template"),
    path("api/plans/<str:key>", PlanViewset.as_view({"get": "retrieve"}), name="billing_plan"),
    opt_slash_path("api/billing", BillingViewset.as_view({"get": "retrieve"}), name="billing"),
    opt_slash_path(
        "billing/setup", stripe_checkout_view, name="billing_setup",
    ),  # Redirect to Stripe Checkout to set-up billing (requires session ID)
    opt_slash_path(
        "billing/manage", stripe_billing_portal, name="billing_manage",
    ),  # Redirect to Stripe Customer Portal to manage subscription
    opt_slash_path(
        "billing/welcome", billing_welcome_view, name="billing_welcome",
    ),  # Page with success message after setting up billing
    opt_slash_path(
        "billing/failed", billing_failed_view, name="billing_failed",
    ),  # Page with failure message after attempting to set up billing
    opt_slash_path(
        "billing/hosted", billing_hosted_view, name="billing_hosted",
    ),  # Page with success message after setting up billing for hosted plans
    opt_slash_path("billing/stripe_webhook", stripe_webhook, name="billing_stripe_webhook"),  # Stripe Webhook
    opt_slash_path("billing/subscribe", BillingSubscribeViewset.as_view({"post": "create"}), name="billing_subscribe"),
]

# Include base `posthog` routes
urlpatterns += posthog_urls
