from django.db import models
from django.conf import settings

class EmailedUser(models.Model):
    user_email: models.CharField = models.CharField(max_length=400)
    has_received_email: models.BooleanField = models.BooleanField(default=False)