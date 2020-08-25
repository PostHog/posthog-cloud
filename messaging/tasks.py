from celery import shared_task
from posthog.models import User, Team
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError
from .mail import Mail    


@shared_task
def check_and_send_event_ingestion_follow_up(user_id: int, team_id: int) -> None:
    """
    Will send a follow up email to any user that has signed up for a team that has not ingested events.
    """

    validator = EmailValidator()

    user = User.objects.get(pk=user_id)
    team = Team.objects.get(pk=team_id)

    # If user has anonymized their data or the email is invalid we ignore it
    if user.anonymize_data:
        return
    
    try:
        validator(user.email)
    except ValidationError:
        return

    if team.event_set.exists():
        # Team has ingested events, no email necessary
        return
    
    Mail.send_event_ingestion_follow_up(user.email)


@shared_task
def process_team_signup_messaging(user_id: int, team_id: int) -> None:
    """
    Processes any logic related to messaging after a user signs up for an account.
    """
    
    # Send event ingestion follow up in 3 hours (if no events have been ingested yet)
    send_event_ingestion_follow_up.apply_async((user_id, team_id), countdown=10800)
