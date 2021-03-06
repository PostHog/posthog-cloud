# These settings get copied by bin/pull_main or bin/develop into the end of settings.py of the main PostHog code base.

MULTI_TENANCY = os.environ.get("MULTI_TENANCY", True)

ROOT_URLCONF = "multi_tenancy.urls"

if INSTALLED_APPS and isinstance(INSTALLED_APPS, list):

    INSTALLED_APPS.append("multi_tenancy.apps.MultiTenancyConfig")
    INSTALLED_APPS.append("messaging.apps.MessagingConfig")

if TEMPLATES and TEMPLATES[0] and TEMPLATES[0]["DIRS"] and isinstance(TEMPLATES[0]["DIRS"], list):

    TEMPLATES[0]["DIRS"].insert(0, "multi_tenancy/templates")


EVENT_USAGE_CACHING_TTL = get_from_env("EVENT_USAGE_CACHING_TTL", 12 * 60 * 60, type_cast=int)


# Stripe settings
# https://github.com/stripe/stripe-python

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


# Business rules
# https://github.com/posthog/posthog-production

BILLING_TRIAL_DAYS = get_from_env("BILLING_TRIAL_DAYS", 0, type_cast=int)
BILLING_NO_PLAN_EVENT_ALLOCATION = get_from_env("BILLING_NO_PLAN_EVENT_ALLOCATION", optional=True, type_cast=int)

MIDDLEWARE.append("multi_tenancy.middleware.PostHogTokenCookieMiddleware")
