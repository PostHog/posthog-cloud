from unittest.mock import patch

from django.core import mail

from posthog.api.test.base import TransactionBaseTest
from posthog.models import Team, User


class TestTeamSignup(TransactionBaseTest):
    pass
