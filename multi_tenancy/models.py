from typing import Optional, Tuple

from django.db import models
from django.utils import timezone

from multi_tenancy.stripe import create_subscription, create_zero_auth
from posthog.models import Team


class Plan(models.Model):
    key: models.CharField = models.CharField(
        max_length=32, unique=True, db_index=True,
    )
    name: models.CharField = models.CharField(max_length=128)
    default_should_setup_billing: models.BooleanField = models.BooleanField(
        default=False,
    )
    custom_setup_billing_message: models.TextField = models.TextField(blank=True)
    price_id: models.CharField = models.CharField(max_length=128)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def create_checkout_session(
        self, user, team_billing, base_url: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Creates a checkout session for the specified plan.
        Uses any custom logic specific to the plan if configured.
        """

        if self.key == "startup":
            # For the startup plan we only do a card validation (no subscription)
            return create_zero_auth(
                email=user.email,
                base_url=base_url,
                customer_id=team_billing.stripe_customer_id,
            )

        return create_subscription(
            email=user.email,
            base_url=base_url,
            price_id=self.price_id,
            customer_id=team_billing.stripe_customer_id,
        )


class TeamBilling(models.Model):

    team: models.OneToOneField = models.OneToOneField(Team, on_delete=models.CASCADE)
    stripe_customer_id: models.CharField = models.CharField(max_length=128, blank=True)
    stripe_checkout_session: models.CharField = models.CharField(
        max_length=128, blank=True,
    )
    checkout_session_created_at: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, default=None,
    )
    should_setup_billing: models.BooleanField = models.BooleanField(default=False)
    billing_period_ends: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, default=None,
    )
    plan: models.ForeignKey = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True,
    )

    @property
    def is_billing_active(self):
        return self.billing_period_ends and self.billing_period_ends > timezone.now()

    @property
    def price_id(self):
        if self.plan:
            return self.plan.price_id
        return ""
