import posthoganalytics
from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from posthog.models import Organization, User, Event

from .mail import Mail
from .models import UserMessagingRecord


@shared_task
def check_and_send_no_event_ingestion_follow_up(
    user_id: int, dummy # temporary dummy arg to retain compatibilty with tasks queued pre-merge that still have 2 args
) -> None:
    """Send a follow-up email to a user whose all teams still have no events."""
    campaign: str = UserMessagingRecord.NO_EVENT_INGESTION_FOLLOW_UP

    try:
        user: User = User.objects.get(id=user_id)
    except User.DoesNotExist:
        # if user removed their account, email useless
        return

    # If user has anonymized their data, email unwanted
    if user.anonymize_data:
        return

    # If any team the user belongs to has ingested events, email unnecessary
    for team in user.teams.all():
        if team.event_set.exists():
            return

    # If user's email address is invalid, email impossible
    try:
        validate_email(user.email)
    except ValidationError:
        return

    record, created = UserMessagingRecord.objects.get_or_create(
        user=user, campaign=campaign,
    )

    with transaction.atomic():
        # Lock object (database-level) while the message is sent
        record = UserMessagingRecord.objects.select_for_update().get(pk=record.pk)
        # If an email for this campaign was already sent to this user, email unwanted
        if record.sent_at:
            return
        Mail.send_no_event_ingestion_follow_up(user.email, user.first_name)
        record.sent_at = timezone.now()
        record.save()

    posthoganalytics.capture(
        user.distinct_id, f"sent campaign {campaign}", properties={"medium": "email"},
    )


@shared_task
def process_organization_signup_messaging(user_id: int, organization_id: str) -> None:
    """Process messaging for recently created organizations."""
    # Send event ingestion follow-up in 24 hours, if no events have been ingested by that time
    check_and_send_no_event_ingestion_follow_up.apply_async(
        (user_id, organization_id), countdown=86_400,
    )
