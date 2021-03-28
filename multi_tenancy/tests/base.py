import random
import uuid

from ee.clickhouse.models.event import create_event
from multi_tenancy.models import Plan
from posthog.models import Team, User
from posthog.test.base import APIBaseTest, BaseTest


class CloudMixin:
    def event_factory(self, team: Team, quantity: int = 1):

        for _ in range(0, quantity):
            create_event(
                team=team,
                event=random.choice(["$pageview", "$autocapture", "order completed"]),
                distinct_id=f"distinct_id_{random.randint(100,999)}",
                event_uuid=uuid.uuid4(),
            )

    def create_org_team_user(self):
        return User.objects.bootstrap(
            organization_name="Z",
            first_name="X",
            email=f"user{random.randint(100, 999)}@posthog.com",
            password=self.CONFIG_PASSWORD,
            team_fields={"api_token": f"token_{random.randint(100000, 999999)}"},
        )

    def create_plan(self, **kwargs):
        return Plan.objects.create(
            **{
                "key": f"plan_{random.randint(100000, 999999)}",
                "price_id": f"price_{random.randint(1000000, 9999999)}",
                "name": "Test Plan",
                **kwargs,
            },
        )


class CloudBaseTest(CloudMixin, BaseTest):
    pass


class CloudAPIBaseTest(CloudMixin, APIBaseTest):
    pass
