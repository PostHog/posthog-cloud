from typing import Dict, Optional

from messaging.tasks import process_organization_signup_messaging
from posthog.api.team import TeamSignupSerializer
from posthog.models import User
from posthog.templatetags.posthog_filters import compact_number
from rest_framework import serializers

from .models import OrganizationBilling, Plan


class ReadOnlySerializer(serializers.ModelSerializer):
    def create(self, validated_data: Dict):
        raise NotImplementedError()

    def update(self, validated_data: Dict):
        raise NotImplementedError()


class MultiTenancyOrgSignupSerializer(TeamSignupSerializer):
    plan = serializers.CharField(max_length=32, required=False)

    def validate_plan(self, data: Dict) -> Optional[Plan]:
        try:
            return Plan.objects.get(key=data)
        except Plan.DoesNotExist:
            return None

    def create(self, validated_data: Dict) -> User:
        plan = validated_data.pop("plan", None)
        user = super().create(validated_data)

        process_organization_signup_messaging.delay(
            user_id=user.pk, organization_id=str(self._organization.id)
        )

        if plan:
            OrganizationBilling.objects.create(
                organization=self._organization,
                plan=plan,
                should_setup_billing=plan.default_should_setup_billing,
            )

        return user


class PlanSerializer(serializers.ModelSerializer):
    allowance = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "key",
            "name",
            "custom_setup_billing_message",
            "allowance",
            "image_url",
            "self_serve",
        ]

    def get_allowance(self, obj: Plan) -> Optional[Dict]:
        if not obj.event_allowance:
            return None
        return {
            "value": obj.event_allowance,
            "formatted": compact_number(obj.event_allowance),
        }
