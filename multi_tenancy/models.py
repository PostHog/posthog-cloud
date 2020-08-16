from django.db import models
from django.conf import settings
from django.utils import timezone
from posthog.models.team import Team

class TeamBilling(models.Model):

    team: models.OneToOneField = models.OneToOneField(Team, on_delete=models.CASCADE)
    stripe_customer_id: models.CharField = models.CharField(max_length=128, blank=True)
    stripe_checkout_session: models.CharField = models.CharField(
        max_length=128, blank=True
    )
    should_setup_billing: models.BooleanField = models.BooleanField(default=False)
    billing_period_ends: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, default=None
    )
    price_id: models.CharField = models.CharField(max_length=128, blank=True, default="")

    @property
    def is_billing_active(self):
        return self.billing_period_ends and self.billing_period_ends > timezone.now()
