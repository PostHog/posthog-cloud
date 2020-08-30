from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from posthog.models import Team, User
from .models import UserMessagingState

from .mail import Mail
import posthoganalytics


@shared_task
def check_and_send_event_ingestion_follow_up(user_id: int, team_id: int) -> None:
    """Send a follow-up email to a user that has signed up for a team that has not ingested events yet."""
    user = User.objects.select_related('messaging_state').get(pk=user_id)
    team = Team.objects.get(pk=team_id)
    if user.messaging_state is not None:
        messaging_state = user.messaging_state
    else:
        messaging_state = UserMessagingState(user=user)
    # If user has anonymized their data, email unwanted
    if user.anonymize_data: return
    # If team has ingested events, email unnecessary
    if team.event_set.exists(): return
    # If user's email address is invalid, email impossible
    try:
        validate_email(user.email)
    except ValidationError:
        return
    # If a follow-up email has already been sent, email unwanted
    if messaging_state.was_no_event_ingestion_mail_sent:
        return

    try:
        Mail.send_event_ingestion_follow_up(user.email, user.first_name)
    except Exception as e:
        raise e
    else:
        messaging_state.was_no_event_ingestion_mail_sent = True
        posthoganalytics.capture(user.distinct_id, "sent no event ingestion email")
    finally:
        messaging_state.save()



@shared_task
def process_team_signup_messaging(user_id: int, team_id: int) -> None:
    """Process messaging of signed-up users."""
    # Send event ingestion follow up in 3 hours (if no events have been ingested by that time)
    check_and_send_event_ingestion_follow_up.apply_async(
        (user_id, team_id), countdown=10800
    )
