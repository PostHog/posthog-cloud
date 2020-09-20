from typing import Optional
from django.db import models
from django.utils import timezone
from posthog.models import Team, Organization



class Plan(models.Model):
    key: models.CharField = models.CharField(
        max_length=32, unique=True, db_index=True,
    )
    name: models.CharField = models.CharField(max_length=128)
    default_should_setup_billing: models.BooleanField = models.BooleanField(
        default=False,
    )
    price_id: models.CharField = models.CharField(
        max_length=128, blank=True, default="",
    )


class TeamBilling(models.Model):
    """DEPRECATED: Organization is now the root entity, so TeamBilling has been replaced with BilledOrganization."""

    team: models.OneToOneField = models.OneToOneField(Team, on_delete=models.CASCADE)
    stripe_customer_id: models.CharField = models.CharField(max_length=128, blank=True)
    stripe_checkout_session: models.CharField = models.CharField(
        max_length=128, blank=True,
    )
    should_setup_billing: models.BooleanField = models.BooleanField(default=False)
    billing_period_ends: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, default=None,
    )
    plan: models.ForeignKey = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True,
    )
    price_id: models.CharField = models.CharField(
        max_length=128, blank=True, default=""
    )

    @property
    def is_billing_active(self) -> bool:
        return self.billing_period_ends and self.billing_period_ends > timezone.now()

    def get_price_id(self) -> str:
        if self.plan:
            return self.plan.price_id
        return self.price_id or ""


class BilledOrganization(Organization):
    """An extension to Organization for handling PostHog Cloud billing."""

    organization: models.OneToOneField = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        parent_link=True,
        primary_key=True,
        related_name="billing",
    )
    stripe_customer_id: models.CharField = models.CharField(max_length=128, blank=True)
    stripe_checkout_session: models.CharField = models.CharField(
        max_length=128, blank=True
    )
    should_setup_billing: models.BooleanField = models.BooleanField(default=False)
    billing_period_ends: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, default=None
    )
    plan: models.ForeignKey = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True,
    )
    price_id: models.CharField = models.CharField(
        max_length=128, blank=True, default=""
    )

    @property
    def is_billing_active(self) -> bool:
        return self.billing_period_ends and self.billing_period_ends > timezone.now()

    def get_price_id(self) -> str:
        if self.plan:
            return self.plan.price_id
        return self.price_id or ""
