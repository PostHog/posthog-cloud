import posthoganalytics
from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from posthog.models import Organization, User

from .mail import Mail
from .models import UserMessagingRecord


@shared_task
def check_and_send_no_event_ingestion_follow_up(user_id: int, organization_id: str) -> None:
    """Send a follow-up email to a user that has signed up for a team that has not ingested events yet."""
    campaign: str = UserMessagingRecord.NO_EVENT_INGESTION_FOLLOW_UP

    user: User = User.objects.get(id=user_id)
    organization: Organization = Organization.objects.get(id=organization_id)

    # If user has anonymized their data, email unwanted
    if user.anonymize_data:
        return

    # If any team belonging to organization has ingested events, email unnecessary
    for team in organization.teams.all():
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

        # If an email for this campaign was already sent, email unwanted
        if record.sent_at:
            return

        Mail.send_no_event_ingestion_follow_up(user.email, user.first_name)
        record.sent_at = timezone.now()
        record.save()

    posthoganalytics.capture(
        user.distinct_id, f"sent campaign {campaign}", properties={"medium": "email"},
    )


@shared_task
def process_team_signup_messaging(user_id: int, organization_id: str) -> None:
    """Process messaging of signed-up users."""
    # Send event ingestion follow-up in 24 hours, if no events have been ingested by that time
    check_and_send_no_event_ingestion_follow_up.apply_async(
        (user_id, organization_id), countdown=86_400,
    )
