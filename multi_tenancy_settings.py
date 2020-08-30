# These settings get copied by bin/pull_posthog into the end of settings.py of the main PostHog code base.

MULTI_TENANCY = os.environ.get("MULTI_TENANCY", True)

ROOT_URLCONF = "multi_tenancy.urls"

if INSTALLED_APPS and isinstance(INSTALLED_APPS, list):

    INSTALLED_APPS.append("multi_tenancy.apps.MultiTenancyConfig")

if (
    TEMPLATES
    and TEMPLATES[0]
    and TEMPLATES[0]["DIRS"]
    and isinstance(TEMPLATES[0]["DIRS"], list)
):

    TEMPLATES[0]["DIRS"].append("multi_tenancy/templates")


# Stripe settings
# https://github.com/stripe/stripe-python

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_GROWTH_PRICE_ID = os.environ.get("STRIPE_GROWTH_PRICE_ID", "")
