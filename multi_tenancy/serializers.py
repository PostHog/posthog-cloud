from messaging.tasks import process_organization_signup_messaging
from posthog.api.team import TeamSignupSerializer
from rest_framework import serializers

from .models import OrganizationBilling, Plan


class MultiTenancyOrgSignupSerializer(TeamSignupSerializer):
    plan = serializers.CharField(max_length=32, required=False)

    def validate_plan(self, data):
        try:
            return Plan.objects.get(key=data)
        except Plan.DoesNotExist:
            return None

    def create(self, validated_data):
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
    class Meta:
        model = Plan
        fields = ["key", "name", "custom_setup_billing_message"]
        read_only_fields = ["key", "name", "custom_setup_billing_message"]
