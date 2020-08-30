from django.db import models
from posthog.models import User


class UserMessagingRecord(models.Model):
    NO_EVENT_INGESTION_FOLLOW_UP = 'no_event_ingestion_follow_up'
    CAMPAIGN_CHOICES = [
        (NO_EVENT_INGESTION_FOLLOW_UP, 'No Event Ingestion Follow-Up'),
    ]

    user: models.ForeignKey = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="messaging_records"
    )
    campaign: models.CharField = models.CharField(max_length=64)
    sent_at: models.DateTimeField = models.DateTimeField(null=True, default=None, choices=CAMPAIGN_CHOICES)

    class Meta:
        unique_together = ("user", "campaign")
