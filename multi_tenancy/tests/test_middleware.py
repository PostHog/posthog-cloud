import json
from urllib.parse import quote

from posthog.api.test.base import APIBaseTest
from rest_framework import status


class TestPostHogTokenCookieMiddleware(APIBaseTest):
    def test_logged_out_client(self):
        self.client.logout()
        response = self.client.get("/")
        self.assertEqual(0, len(response.cookies))

    def test_logged_in_client(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ph_project_token_cookie = response.cookies["ph_current_project_token"]
        self.assertEqual(ph_project_token_cookie.key, "ph_current_project_token")
        self.assertEqual(ph_project_token_cookie.value, self.user.team.api_token)
        self.assertEqual(ph_project_token_cookie["path"], "/")
        self.assertEqual(ph_project_token_cookie["samesite"], "Strict")
        self.assertEqual(ph_project_token_cookie["httponly"], "")
        self.assertEqual(ph_project_token_cookie["domain"], "posthog.com")
        self.assertEqual(ph_project_token_cookie["comment"], "")
        self.assertEqual(ph_project_token_cookie["secure"], True)
        self.assertEqual(ph_project_token_cookie["max-age"], 31536000)

        ph_project_name_cookie = response.cookies["ph_current_project_name"]
        self.assertEqual(ph_project_name_cookie.key, "ph_current_project_name")
        self.assertEqual(ph_project_name_cookie.value, self.user.team.name)
        self.assertEqual(ph_project_name_cookie["path"], "/")
        self.assertEqual(ph_project_name_cookie["samesite"], "Strict")
        self.assertEqual(ph_project_name_cookie["httponly"], "")
        self.assertEqual(ph_project_name_cookie["domain"], "posthog.com")
        self.assertEqual(ph_project_name_cookie["comment"], "")
        self.assertEqual(ph_project_name_cookie["secure"], True)
        self.assertEqual(ph_project_name_cookie["max-age"], 31536000)

    def test_ph_project_cookies_are_not_set_on_capture_or_api_endpoints(self):
        self.client.logout()

        data = {
            "event": "user did custom action",
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        response = self.client.get(
            "/e/?data=%s" % quote(json.dumps(data)), content_type="application/json", HTTP_ORIGIN="https://localhost",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

        response = self.client.post(
            "/track/",
            data={
                "data": json.dumps(
                    [{"event": "beep", "properties": {"distinct_id": "eeee", "token": self.team.api_token}}],
                ),
                "api_key": self.team.api_token,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

        self.client.force_login(self.user)

        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

        response = self.client.patch("/api/user/", {"first_name": "Alice"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.cookies["ph_current_project_token"].key, "ph_current_project_token")
        self.assertEqual(response.cookies["ph_current_project_token"].value, self.user.team.api_token)
        self.assertEqual(response.cookies["ph_current_project_token"]["max-age"], 31536000)

        self.assertEqual(response.cookies["ph_current_project_name"].key, "ph_current_project_name")
        self.assertEqual(response.cookies["ph_current_project_name"].value, self.user.team.name)
        self.assertEqual(response.cookies["ph_current_project_name"]["max-age"], 31536000)

        response = self.client.get("/logout")
        self.assertEqual("ph_current_project_token" in response.cookies, False)
        self.assertEqual("ph_current_project_name" in response.cookies, False)
