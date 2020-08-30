from django.db import models
from django.conf import settings
from posthog.models import User

class UserMessagingState(models.Model):
    user: models.OneToOneField = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='messaging_state'
    )
    was_no_event_ingestion_mail_sent: models.BooleanField = models.BooleanField(default=False)
