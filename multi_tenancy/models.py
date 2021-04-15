import datetime
from typing import List, Optional, Tuple

from django.conf import settings
from django.db import models
from django.utils import timezone
from ee.models import License
from posthog.models import Organization, User

from .stripe import create_subscription, create_subscription_checkout_session, create_zero_auth

PLANS = {
    "starter": ["organizations_projects"],
    "growth": License.ENTERPRISE_FEATURES,
    "startup": License.ENTERPRISE_FEATURES,
    "standard": License.ENTERPRISE_FEATURES,
    "enterprise": License.ENTERPRISE_FEATURES,
}


class Plan(models.Model):
    """
    Base model for different plans. Note that custom logic (e.g. doing card validation
    instead of starting a subscription) is registered in the OrganizationBilling object.
    """

    key: models.CharField = models.CharField(
        max_length=32, unique=True, db_index=True,
    )
    name: models.CharField = models.CharField(max_length=128)
    default_should_setup_billing: models.BooleanField = models.BooleanField(
        default=False,
    )  # determines whether `should_setup_billing` should be automatically set to `True` when this plan is assigned to an org
    custom_setup_billing_message: models.TextField = models.TextField(
        blank=True
    )  # displays a custom message (in the UI) when prompting a user to confirm their billing details (e.g. explain the zero-auth charge in startup plan)
    price_id: models.CharField = models.CharField(max_length=128)  # Stripe ID of the relevant price definition
    event_allowance: models.IntegerField = models.IntegerField(
        default=None, null=True, blank=True,
    )  # number of monthly events that this plan allows; use null for unlimited events and metered pricing
    is_active: models.BooleanField = models.BooleanField(default=True)
    is_metered_billing: models.BooleanField = models.BooleanField(
        default=False,
    )  # whether the plan is usaged-based (metered event-based billing) instead of flat-fee recurring billing;
    # https://stripe.com/docs/billing/subscriptions/metered-billing or docs/Billing.md
    self_serve: models.BooleanField = models.BooleanField(
        default=False,
    )  # Whether users can subscribe to this plan by themselves after sign up (i.e. when `False` only PostHog Team can assign this plan)
    image_url: models.URLField = models.URLField(
        max_length=1024, blank=True
    )  # URL of the image for the plan (display purposes)
    price_string: models.CharField = models.CharField(
        max_length=128, blank=True,
    )  # A human-friendly representation of the price of the plan to show on the front-end UI.
    # TODO: Obtain price string dynamically from Stripe to have a centralized source of information

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class OrganizationBilling(models.Model):
    """An extension to Organization for handling PostHog Cloud billing."""

    organization: models.OneToOneField = models.OneToOneField(
        Organization, on_delete=models.CASCADE, primary_key=True, related_name="billing",
    )
    stripe_customer_id: models.CharField = models.CharField(max_length=128, blank=True)
    stripe_checkout_session: models.CharField = models.CharField(
        max_length=128,
        blank=True,
        help_text="ID of the current checkout session. Only relevant during the setup phase."
        " Use `stripe_subscription_id` afterwards.",
    )
    stripe_subscription_id: models.CharField = models.CharField(
        max_length=128, blank=True,
    )
    stripe_subscription_item_id: models.CharField = models.CharField(
        max_length=128, blank=True,
    )  # DEPRECATED: We will use the subscription ID now as tiered or graduated pricing may have multiple items
    checkout_session_created_at: models.DateTimeField = models.DateTimeField(
        null=True, blank=True,
    )
    should_setup_billing: models.BooleanField = models.BooleanField(
        default=False,
        help_text="When this is `True`, the customer will be shown a message prompting them to confirm their"
        " billing details on Stripe; should **always be set if the customer hasn't added billing details.**"
        " Must be set manually if the plan is manually assigned.",
    )
    billing_period_ends: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, help_text="Final date until when this plan will be active."
    )
    plan: models.ForeignKey = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True, default=None, blank=True,
    )

    @property
    def is_billing_active(self) -> bool:
        return bool(
            self.plan
            and not self.should_setup_billing
            and self.billing_period_ends
            and self.billing_period_ends > timezone.now()
        )

    def get_plan_key(self, only_active: bool = True) -> Optional[str]:
        """
        Returns the key of the current plan. If `only_active` it will only return the plan information if billing
        is active.
        """
        if only_active and not self.is_billing_active:
            return None
        return self.plan.key if self.plan else None

    def get_price_id(self) -> str:
        return self.plan.price_id if self.plan else ""

    @property
    def event_allocation(self) -> Optional[int]:
        """
        Returns the event allocation applicable to the organization.
        """
        if not self.is_billing_active:
            # No active billing plan, default to event allocation for when no billing plan is active
            return settings.BILLING_NO_PLAN_EVENT_ALLOCATION
        return self.plan.event_allowance

    @property
    def available_features(self) -> List[str]:
        plan_key = self.get_plan_key()

        if plan_key and plan_key in PLANS:
            return PLANS[plan_key]

        return []

    def create_checkout_session(self, user: User, base_url: str,) -> Tuple[Optional[str], Optional[str]]:
        """
        Creates a checkout session for the specified plan.
        Uses any custom logic specific to the plan if configured.
        """

        # For metered-billing, we do a card setup for future billing, this specifically means that a subscription
        # agreement is not yet created. This is coincidentally the same behavior for the startup plan.
        if self.plan.is_metered_billing or self.plan.key == "startup":
            # For the startup plan we only do a card validation (no subscription)
            return create_zero_auth(email=user.email, base_url=base_url, customer_id=self.stripe_customer_id,)

        return create_subscription_checkout_session(
            email=user.email, base_url=base_url, price_id=self.plan.price_id, customer_id=self.stripe_customer_id,
        )

    def handle_post_card_validation(self) -> "OrganizationBilling":
        """
        Handles logic after a card has been validated.
        """
        if self.plan.key == "startup":
            self.billing_period_ends = timezone.now() + datetime.timedelta(days=365)
            self.should_setup_billing = False
        elif self.plan.is_metered_billing:
            subscription = create_subscription(price_id=self.plan.price_id, customer_id=self.stripe_customer_id)
            self.stripe_subscription_item_id = subscription["subscription_item_id"]
            self.stripe_subscription_id = subscription["subscription_id"]
            self.should_setup_billing = False
        self.save()
        return self
