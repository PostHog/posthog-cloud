from django.db import models

class FollowUpEmail(models.Model):
    team_id: models.IntegerField = models.IntegerField(null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, blank=True
    )