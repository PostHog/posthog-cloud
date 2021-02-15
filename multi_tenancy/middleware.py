from django.contrib.sessions.middleware import SessionMiddleware

default_cookie_options = {
    "max_age": 365 * 24 * 60 * 60,  # one year
    "expires": None,
    "path": "/",
    "domain": "posthog.com",
    "secure": True,
    "samesite": "Strict",
}

api_paths = {"e", "s", "capture", "batch", "decide", "api", "track"}


class PostHogTokenCookieMiddleware(SessionMiddleware):
    """
    Adds two secure cookies to enable auto-filling the current project token on the docs.
    """

    def process_response(self, request, response):
        response = super().process_response(request, response)

        # skip adding the cookie on API requests
        split_request_path = request.path.split("/")
        if len(split_request_path) and split_request_path[1] in api_paths:
            return response

        if request.user and request.user.is_authenticated:
            response.set_cookie(
                key="ph_current_project_token",
                value=request.user.team.api_token,
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options["expires"],
                path=default_cookie_options["path"],
                domain=default_cookie_options["domain"],
                secure=default_cookie_options["secure"],
                samesite=default_cookie_options["samesite"],
            )

            response.set_cookie(
                key="ph_current_project_name",  # clarify which project is active (orgs can have multiple projects)
                value=request.user.team.name,
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options["expires"],
                path=default_cookie_options["path"],
                domain=default_cookie_options["domain"],
                secure=default_cookie_options["secure"],
                samesite=default_cookie_options["samesite"],
            )

        return response
