import re
from typing import ClassVar, Dict, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .models import UserMessagingRecord


class Mail:
    FROM_ADDRESS: ClassVar[str] = "PostHog Team <hey@posthog.com>"
    SLACK_COMMUNITY_LINK: ClassVar[str] = "https://posthog.com/slack"
    DEMO_SESSION_LINK: ClassVar[str] = "https://calendly.com/yakko/demo"
    EMAIL_HEADERS: ClassVar[Dict[str, str]] = {"X-Mailgun-Tag": "product-suggestions"}

    @staticmethod
    def utmify_url(url: str, *, campaign: str, content: Optional[str]) -> str:
        utmified_url = f"{url}{'&' if '?' in url else '?'}utm_source=posthog&utm_medium=email&utm_campaign={campaign}"
        if content:
            utmified_url += f"&utm_content={content}"
        return utmified_url
        
    @classmethod
    def send_no_event_ingestion_follow_up(cls, email_address: str, name: str) -> None:
        campaign: str = UserMessagingRecord.NO_EVENT_INGESTION_FOLLOW_UP
        
        content: str = f"""
        Hey,

        We've noticed you signed up for PostHog Cloud, but *haven't started receiving events yet*.
        We can't wait to have you on board, gaining new insights into how users use YOUR product
        and what could make it even better!

        Running into any issue or feeling uncertain about something? We'd be happy to help you in any way 
        we can – *just reply to this email* and we'll get back to you as soon as possible. If you prefer a more 
        social setting, feel free to join to our Slack community at {cls.SLACK_COMMUNITY_LINK}, where our 
        team is active on a daily basis. For a personal tour of product analytics and experimentation
        with PostHog, schedule a demo session whenever you want on {cls.DEMO_SESSION_LINK} 
        – it'd be a pleasure to show you around.

        So, how are you feeling about PostHog? Set it up now – {cls.utmify_url(settings.SITE_URL, campaign=campaign, content="text")}

        Best,
        PostHog Team

        P.S. If you'd prefer not to receive suggestions like this one from us, unsubscribe here: %tag_unsubscribe_url%
        """

        html_content: str = f"""
        Hey,
        <br/>
        <br/>
        We've noticed you signed up for PostHog Cloud, but <b>haven't started receiving events yet</b>.
        We just can't wait to have you on board, gaining new insights into how users use <i>your</i> product
        and what could make it even better!<br/>
        <br/>
        Running into any issue or feeling uncertain about something? We'd be happy to help you any way 
        we can – <b>just reply to this email</b> and we'll get back to you as soon as possible. If you'd prefer a more 
        social setting, feel free to join to our <a href="{cls.SLACK_COMMUNITY_LINK}">Slack community</a>, 
        where our team is active on a daily basis. For a personal tour of product analytics and experimentation 
        with PostHog, <a href="{cls.DEMO_SESSION_LINK}">schedule a demo session</a> whenever you want 
        – it'd be a pleasure to show you around.<br/>
        <br/>
        So, how are you feeling about PostHog? <a href="{cls.utmify_url(settings.SITE_URL, campaign=campaign, content="html")}">Set it up now.</a><br/>
        <br/>
        Best,<br/>
        PostHog Team<br/>
        <br/>
        P.S. If you'd prefer not to receive suggestions like this one from us, <a href="%tag_unsubscribe_url%">unsubscribe here</a>.
        """

        pattern = re.compile("[^a-zA-Z0-9 ]+")
        email_message = EmailMultiAlternatives(
            subject="Product insights with PostHog are waiting for you",
            body=content,
            from_email=cls.FROM_ADDRESS,
            to=[f"{pattern.sub('', name)} <{email_address}>"],
            headers=cls.EMAIL_HEADERS,
            reply_to=settings.EMAIL_REPLY_TO,
        )
        email_message.attach_alternative(html_content, "text/html")
        email_message.send()
