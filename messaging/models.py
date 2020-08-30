from django.db import models
from posthog.models import User


class UserMessagingRecord(models.Model):

    user: models.ForeignKey = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="messaging_records"
    )
    campaign: models.CharField = models.CharField(max_length=64)
    sent_at: models.DateTimeField = models.DateTimeField(null=True, default=None)

    class Meta:
        unique_together = ("user", "campaign")
