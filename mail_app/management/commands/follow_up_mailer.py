from mail_app.models.follow_up_email import FollowUpEmail
from django.core.management.base import BaseCommand
from django.core.mail import send_mail

from django.conf import settings

from posthog.models import Event, Team, User
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pytz

class Command(BaseCommand):
    help = 'Check user statuses and send email if necessary'

    def handle(self, *args, **options):
        date_from = datetime.now(pytz.utc) - relativedelta(days=3)
        all_teams = Team.objects.filter(created_at__gte=date_from).all()
        for team in all_teams:
            team_has_events = Event.objects.filter(team=team).exists()
            count = FollowUpEmail.objects.filter(team_id=team.pk).count()
            delta = datetime.now(pytz.utc) - team.created_at
            if not team_has_events and delta.days >= 2 and team.created_at and count < 1:
                self._send_follow_up_to_team(team, count)

    def _send_follow_up_to_team(self, team: Team, count: int):
        for user in team.users.all():
            self._send_follow_up_to_user(user)
        
        FollowUpEmail.objects.create(team_id=team.pk)
    
    def _send_follow_up_to_user(self, recipient: User):
        try:
            send_mail(
                'Follow Up Email',
                'Hi {}, \n\nLooks like you haven\'t started sending events with Posthog yet. Let us know if you want a demo from the team! We\'re happy to get you started on Posthog?'.format(recipient.first_name),
                settings.DEFAULT_FROM_EMAIL,
                [recipient.email])
        except:
            pass