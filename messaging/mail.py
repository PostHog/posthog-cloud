from typing import ClassVar

from django.conf import settings
from django.core.mail import send_mail


class Mail:

    FROM_ADDRESS: ClassVar[str] = "PostHog Team <hey@posthog.com>"
    SLACK_COMMUNITY_LINK: ClassVar[str] = "https://join.slack.com/t/posthogusers/shared_invite/en"
    "QtOTY0MzU5NjAwMDY3LTc2MWQ0OTZlNjhkODk3ZDI3NDVjMDE1YjgxY2I4ZjI4MzJhZmVmNjJkN2NmMGJmMzc2N2U3Yjc3ZjI5NGFlZDQ"
    DEMO_SESSION_LINK: ClassVar[str] = "https://calendly.com/timgl/30min"

    @classmethod
    def send_event_ingestion_follow_up(cls, email: str):

        body: str = """
        Hey,
        <br/>
        <br/>
        We noticed that you signed up for PostHog but <b>haven't started receiving events</b>.
        You'll be able to obtain insights into your users as soon you finish this setup.
        You can review the linking instructions on the <a href="%s">app</a>.
        <br />
        <br/>
        We're happy to help if you have any questions or are running into any
        issues, <b>just reply to this email</b>. If you're in a rush, you can always
        join our <a href="%s">community on Slack</a>.
        <br />
        <br/>
        If you prefer to <a href="%s">schedule a demo session</a>, we'll be happy to show you around.
        <br />
        <br />
        Best,
        <br />
        PostHog Team
        """ % (settings.SITE_URL, cls.SLACK_COMMUNITY_LINK, cls.DEMO_SESSION_LINK)

        send_mail(
            subject="Need any help getting set up?",
            message=body,
            from_email=cls.FROM_ADDRESS,
            recipient_list=[email],
            html_message=body,
            fail_silently=False,
        )
