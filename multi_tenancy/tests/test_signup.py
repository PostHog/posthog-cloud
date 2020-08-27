from posthog.api.test.base import TransactionBaseTest
from django.core import mail
from posthog.models import Team, User
from unittest.mock import patch


class TestTeamSignup(TransactionBaseTest):
    @patch("multi_tenancy.views.posthoganalytics.capture")
    @patch("messaging.tasks.process_team_signup_messaging.delay")
    def test_user_signs_up_for_team(self, mock_messaging, mock_capture):

        response = self.client.post(
            "/signup",
            {
                "name": "John Hedgehog",
                "email": "hedgehog@posthog.com",
                "password": "NotSecure1",
                "company_name": "Hedgehogs United, LLC",
            },
        )
        self.assertRedirects(response, "/")

        user = User.objects.last()
        team = Team.objects.last()

        self.assertEqual(user.first_name, "John Hedgehog")
        self.assertEqual(user.email, "hedgehog@posthog.com")
        self.assertIn(user, team.users.all())
        self.assertEqual(team.name, "Hedgehogs United, LLC")

        # Check that the process_team_signup_messaging task was fired
        mock_messaging.assert_called_once_with(user_id=user.pk, team_id=team.pk)

        # Check that we send the sign up event to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user signed up",
            properties={"is_first_user": False, "is_team_first_user": True},
        )

