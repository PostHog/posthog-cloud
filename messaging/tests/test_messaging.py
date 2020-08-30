from django.core import mail
from django.db.utils import IntegrityError
from django.utils import timezone

from messaging.tasks import check_and_send_no_event_ingestion_follow_up
from messaging.models import UserMessagingRecord
from posthog.api.test.base import BaseTest
from posthog.models import Event, Team, User



class TestMessaging(BaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.team: Team = Team.objects.create()
        cls.user: User = User.objects.create(
            email="test@posthog.com", first_name="John Test"
        )
        cls.team.users.add(cls.user)
        cls.team.save()

    def test_cannot_send_the_same_campaign_twice_to_the_same_user(self):
        user: User = User.objects.create(email="valid@posthog.com")
        UserMessagingRecord.objects.create(user=user, campaign="test_campaign")

        with self.assertRaises(IntegrityError) as e:
            UserMessagingRecord.objects.create(user=user, campaign="test_campaign")
        self.assertIn(
            'duplicate key value violates unique constraint "messaging_usermessagingrecord',
            str(e.exception),
        )

    def test_check_and_send_no_event_ingestion_follow_up(self):
        with self.settings(SITE_URL="https://app.posthog.com"):
            check_and_send_no_event_ingestion_follow_up(self.user.pk, self.team.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].subject, "Product insights with PostHog are waiting for you"
        )
        self.assertEqual(mail.outbox[0].from_email, "PostHog Team <hey@posthog.com>")
        self.assertEqual(mail.outbox[0].to, ["John Test <test@posthog.com>"])
        self.assertIn(
            "haven't started receiving events yet", mail.outbox[0].body,
        )
        self.assertIn(
            "it'd be a pleasure to show you around", mail.outbox[0].body,
        )
        self.assertIn(
            "https://app.posthog.com", mail.outbox[0].body,
        )

    def test_does_not_send_event_ingestion_email_if_team_has_ingested_events(self):
        # Object setup
        team: Team = Team.objects.create()
        user: User = User.objects.create(email="test3@posthog.com")
        team.users.add(user)
        team.save()
        Event.objects.create(team=team)

        check_and_send_no_event_ingestion_follow_up(user.pk, team.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_does_not_send_event_ingestion_email_on_invalid_address(self):
        user: User = User.objects.create(email="a2a8191d-5af9-4473-a44c-4608285a9b7c")
        self.team.users.add(user)
        self.team.save()

        check_and_send_no_event_ingestion_follow_up(user.pk, self.team.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_does_not_send_event_ingestion_email_if_user_is_anonymized(self):
        user: User = User.objects.create(email="valid@posthog.com", anonymize_data=True)
        self.team.users.add(user)
        self.team.save()

        check_and_send_no_event_ingestion_follow_up(user.pk, self.team.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_does_not_send_event_ingestion_email_if_user_has_received_email_before(
        self,
    ):
        user: User = User.objects.create(email="valid@posthog.com")
        self.team.users.add(user)
        self.team.save()

        for i in range(0, 3):
            check_and_send_no_event_ingestion_follow_up(user.pk, self.team.pk)
        self.assertEqual(len(mail.outbox), 1)  # just one email was sent

    def test_event_ingestion_email_is_sent_again_if_previous_attempt_failed(self,):
        user: User = User.objects.create(email="valid@posthog.com")
        self.team.users.add(user)
        self.team.save()
        UserMessagingRecord.objects.create(
            user=user,
            campaign=UserMessagingRecord.NO_EVENT_INGESTION_FOLLOW_UP,  # sent_at = None (i.e. has not been sent)
        )

        check_and_send_no_event_ingestion_follow_up(user.pk, self.team.pk)
        self.assertEqual(len(mail.outbox), 1)  # email was sent
