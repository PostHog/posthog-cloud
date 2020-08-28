from typing import ClassVar

from django.conf import settings
from django.core.mail import send_mail


class Mail:
    FROM_ADDRESS: ClassVar[str] = "PostHog Team <hey@posthog.com>"
    SLACK_COMMUNITY_LINK: ClassVar[str] = "https://join.slack.com/t/posthogusers/shared_invite/en"
    "QtOTY0MzU5NjAwMDY3LTc2MWQ0OTZlNjhkODk3ZDI3NDVjMDE1YjgxY2I4ZjI4MzJhZmVmNjJkN2NmMGJmMzc2N2U3Yjc3ZjI5NGFlZDQ"
    DEMO_SESSION_LINK: ClassVar[str] = "https://calendly.com/timgl/30min"

    @classmethod
    def send_event_ingestion_follow_up(cls, email: str, name: str) -> None:
        message: str = f"""
        Hey, {name}!

        We've noticed you signed up for PostHog Cloud, but *haven't started receiving events yet*.
        And we just can't wait to have you on board, gaining new insights into how users use YOUR product
        and what could make it even better!
        Open PostHog at {settings.SITE_URL} and have a go at setting up event autocapture from the frontend,
        integrating analytics using one of our many libraries, or simply tapping into our HTTP API.

        Running into any issue or feeling uncertain about something? We'd be delighted to help you any way we can – *just reply to this email* and we'll get to you as soon as possible.
        If you'd prefer a more social setting, feel invited to our Slack community at {cls.SLACK_COMMUNITY_LINK}, where the PostHog Team is active as well.
        And for a personal tour of product analytics and experimentation with PostHog, schedule a demo session whenever you want with {cls.DEMO_SESSION_LINK} – it'd be a pleasure to show you around.

        So, how are you feeling about PostHog? Set it up now – {settings.SITE_URL}

        Best,
        PostHog Team
        """
    
        html_message: str = f"""
        Hey, {name}!<br/>
        <br/>
        We've noticed you signed up for PostHog Cloud, but <b>haven't started receiving events yet</b>.
        And we just can't wait to have you on board, gaining new insights into how users use <i>your</i> product
        and what could make it even better!<br\>
        <a href="{settings.SITE_URL}">Open PostHog and have a go at setting up event autocapture from the frontend,
        integrating analytics using one of our many libraries, or simply tapping into our HTTP API.</a><br/>
        <br/>
        Running into any issue or feeling uncertain about something? We'd be delighted to help you any way we can – <b>just reply to this email</b> and we'll get to you as soon as possible.<br\>
        If you'd prefer a more social setting, <a href="{cls.SLACK_COMMUNITY_LINK}">feel invited to our Slack community</a>, where the PostHog Team is active as well.<br/>
        And for a personal tour of product analytics and experimentation with PostHog, <a href="{cls.DEMO_SESSION_LINK}">schedule a demo session whenever you want</a> – it'd be a pleasure to show you around.<br/>
        <br/>
        So, how are you feeling about PostHog? <a href="{settings.SITE_URL}">Set it up now.</a><br/>
        <br/>
        Best,<br/>
        PostHog Team
        """

        send_mail(
            subject="Product insights with PostHog are waiting for you",
            message=message,
            from_email=cls.FROM_ADDRESS,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False
        )
