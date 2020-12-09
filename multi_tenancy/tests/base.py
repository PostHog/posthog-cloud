import random
import uuid
from typing import Tuple

from ee.clickhouse.models.event import create_event
from multi_tenancy.models import Plan
from posthog.models import Organization, Team, User


class FactoryMixin:
    def create_org_and_team(self) -> Tuple[Organization, Team]:
        org = Organization.objects.create()
        team = Team.objects.create(organization=org)
        return (org, team)

    def event_factory(self, team: Team, quantity: int = 1):

        for _ in range(0, quantity):
            create_event(
                team=team,
                event=random.choice(["$pageview", "$autocapture", "order completed"]),
                distinct_id=f"distinct_id_{random.randint(100,999)}",
                event_uuid=uuid.uuid4(),
            )


class PlanTestMixin:
    def create_org_team_user(self):
        return User.objects.bootstrap(
            company_name="Z",
            first_name="X",
            email=f"user{random.randint(100, 999)}@posthog.com",
            password=self.TESTS_PASSWORD,
            team_fields={"api_token": "token789"},
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

