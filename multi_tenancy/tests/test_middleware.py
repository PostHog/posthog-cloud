from django.conf import settings
from django.test import Client, TestCase
from rest_framework import status

from posthog.test.base import BaseTest


class TestPosthogTokenCookieMiddleware(BaseTest):
    TESTS_API = True
    TESTS_FORCE_LOGIN = False

    def test_logged_out_client(self):
        response = self.client.get("/")
        self.assertEqual(0, len(response.cookies))

    def test_logged_in_client(self):
        self.client.force_login(self.user)
        response = self.client.get("/")

        ph_project_token_cookie = response.cookies['ph_current_project_token']
        self.assertEqual(ph_project_token_cookie.key, 'ph_current_project_token')
        self.assertEqual(ph_project_token_cookie.value, self.user.team.api_token)
        self.assertEqual(ph_project_token_cookie["path"], "/")
        self.assertEqual(ph_project_token_cookie["samesite"], "None")
        self.assertEqual(ph_project_token_cookie["httponly"], True)
        self.assertEqual(ph_project_token_cookie["domain"], "")
        self.assertEqual(ph_project_token_cookie["comment"], "")
        self.assertEqual(ph_project_token_cookie["secure"], True)
        self.assertEqual(ph_project_token_cookie["max-age"], 31536000)

        ph_project_name_cookie = response.cookies['ph_current_project_name']
        self.assertEqual(ph_project_name_cookie.key, 'ph_current_project_name')
        self.assertEqual(ph_project_name_cookie.value, self.user.team.name)
        self.assertEqual(ph_project_name_cookie["path"], "/")
        self.assertEqual(ph_project_name_cookie["samesite"], "None")
        self.assertEqual(ph_project_name_cookie["httponly"], True)
        self.assertEqual(ph_project_name_cookie["domain"], "")
        self.assertEqual(ph_project_name_cookie["comment"], "")
        self.assertEqual(ph_project_name_cookie["secure"], True)
        self.assertEqual(ph_project_name_cookie["max-age"], 31536000)

    def test_logged_in_client_secure(self):
        self.client.force_login(self.user)

        response = self.client.get("/")
        ph_project_token_cookie = response.cookies['ph_current_project_token']
        self.assertEqual(ph_project_token_cookie.key, 'ph_current_project_token')
        self.assertEqual(ph_project_token_cookie.value, self.user.team.api_token)
        self.assertEqual(ph_project_token_cookie["path"], "/")
        self.assertEqual(ph_project_token_cookie["samesite"], "None")
        self.assertEqual(ph_project_token_cookie["httponly"], True)
        self.assertEqual(ph_project_token_cookie["domain"], "")
        self.assertEqual(ph_project_token_cookie["comment"], "")
        self.assertEqual(ph_project_token_cookie["secure"], True)
        self.assertEqual(ph_project_token_cookie["max-age"], 31536000)

        ph_project_name_cookie = response.cookies['ph_current_project_name']
        self.assertEqual(ph_project_name_cookie.key, 'ph_current_project_name')
        self.assertEqual(ph_project_name_cookie.value, self.user.team.name)
        self.assertEqual(ph_project_name_cookie["path"], "/")
        self.assertEqual(ph_project_name_cookie["samesite"], "None")
        self.assertEqual(ph_project_name_cookie["httponly"], True)
        self.assertEqual(ph_project_name_cookie["domain"], "")
        self.assertEqual(ph_project_name_cookie["comment"], "")
        self.assertEqual(ph_project_name_cookie["secure"], True)
        self.assertEqual(ph_project_name_cookie["max-age"], 31536000)

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.cookies['ph_current_project_token'].key, "ph_current_project_token")
        self.assertEqual(response.cookies['ph_current_project_token'].value, self.user.team.api_token)
        self.assertEqual(response.cookies['ph_current_project_token']["max-age"], 31536000)

        self.assertEqual(response.cookies['ph_current_project_name'].key, "ph_current_project_name")
        self.assertEqual(response.cookies['ph_current_project_name'].value, self.user.team.name)
        self.assertEqual(response.cookies['ph_current_project_name']["max-age"], 31536000)

        response = self.client.get("/logout")
        self.assertEqual('ph_current_project_token' in response.cookies, False)
        self.assertEqual('ph_current_project_name' in response.cookies, False)

