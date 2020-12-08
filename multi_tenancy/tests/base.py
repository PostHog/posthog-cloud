import random

from multi_tenancy.models import Plan
from posthog.models import User


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

