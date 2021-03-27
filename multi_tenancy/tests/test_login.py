from multi_tenancy.tests.base import CloudAPIBaseTest
from posthog.models import User
from rest_framework import status


class TestLogin(CloudAPIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def test_login(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "user1@posthog.com")

    def test_login_without_team(self):
        teamless_user = User.objects.create_user(first_name="test", email="user2@posthog.com", password="12345678")
        teamless_user._team = None
        teamless_user.save()
        self.client.force_login(teamless_user)
        response = self.client.get("/api/user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "user2@posthog.com")
        self.assertEqual(response.json()["team"], None)
        self.assertEqual(len(response.json()["teams"]), 0)

