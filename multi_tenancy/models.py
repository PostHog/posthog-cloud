from django.db import models
from django.utils import timezone

from posthog.models.team import Team


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

    @property
    def is_billing_active(self):
        return self.billing_period_ends and self.billing_period_ends > timezone.now()

    @property
    def price_id(self):
        if self.plan:
            return self.plan.price_id
        return ""
