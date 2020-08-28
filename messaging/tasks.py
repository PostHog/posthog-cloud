from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from posthog.models import Team, User

from .mail import Mail
import posthoganalytics


@shared_task
def check_and_send_event_ingestion_follow_up(user_id: int, team_id: int) -> None:
    """Send a follow-up email to a user that has signed up for a team that has not ingested events yet."""
    user = User.objects.get(pk=user_id)
    team = Team.objects.get(pk=team_id)
    # If user has anonymized their data, email unwanted
    if user.anonymize_data:
        return
    # If team has ingested events, email unnecessary
    if team.event_set.exists():
        return
    # If user's email address is invalid, email impossible
    try:
        validate_email(user.email)
    except ValidationError:
        return
    Mail.send_event_ingestion_follow_up(user.email, user.first_name)
    posthoganalytics.capture(user.distinct_id, "sent no event ingestion email")


@shared_task
def process_team_signup_messaging(user_id: int, team_id: int) -> None:
    """Process messaging of signed-up users."""
    # Send event ingestion follow up in 3 hours (if no events have been ingested by that time)
    check_and_send_event_ingestion_follow_up.apply_async(
        (user_id, team_id), countdown=10800
    )
