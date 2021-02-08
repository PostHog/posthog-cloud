from django.contrib.sessions.middleware import SessionMiddleware

default_cookie_options = {
    'max_age': 365 * 24 * 60 * 60,  # max_age = one year
    'expires': None,  # expires
    'path': "/",  # path
    'domain': None,  # domain
    'secure': True,  # secure
    'httponly': True,  # httponly
    'samesite': "Lax",  # samesite, can't be set to "None" here :(
}


class PosthogTokenCookieMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        response = super(PosthogTokenCookieMiddleware, self).process_response(request, response)

        # skip adding the cookie on API requests
        if request.path.startswith("/api/") or request.path.startswith("/e/") or request.path.startswith("/decide/"):
            return response

        if (request.user and request.user.is_authenticated):
            response.set_cookie(
                key='ph_current_project_token',
                value=request.user.team.api_token,
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options['expires'],
                path=default_cookie_options['path'],
                domain=default_cookie_options['domain'],
                secure=default_cookie_options['secure'],
                httponly=default_cookie_options['httponly'],
                samesite=default_cookie_options['samesite']
            )
            response.set_cookie(
                key='ph_current_project_name', # needed to tell users what token they are seeing
                value=request.user.team.name,
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options['expires'],
                path=default_cookie_options['path'],
                domain=default_cookie_options['domain'],
                secure=default_cookie_options['secure'],
                httponly=default_cookie_options['httponly'],
                samesite=default_cookie_options['samesite']
            )

            # must be set separately
            response.cookies['ph_current_project_token']["samesite"] = "None"  
            response.cookies['ph_current_project_name']["samesite"] = "None" 
    
        return response
