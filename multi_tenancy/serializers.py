from typing import Any, Dict, Optional

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from messaging.tasks import process_organization_signup_messaging
from posthog.api.organization import OrganizationSignupSerializer
from posthog.models import User
from posthog.templatetags.posthog_filters import compact_number
from rest_framework import serializers
from sentry_sdk import capture_exception

from .models import OrganizationBilling, Plan


class ReadOnlySerializer(serializers.ModelSerializer):
    def create(self, validated_data: Dict):
        raise NotImplementedError()

    def update(self, validated_data: Dict):
        raise NotImplementedError()


class MultiTenancyOrgSignupSerializer(OrganizationSignupSerializer):
    plan = serializers.CharField(max_length=32, required=False)

    def validate_plan(self, data: Dict) -> Optional[Plan]:
        try:
            return Plan.objects.get(key=data)
        except Plan.DoesNotExist:
            return None

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already in use.", code="unique")
        return value

    def create(self, validated_data: Dict) -> User:
        plan = validated_data.pop("plan", None)
        user = super().create(validated_data)

        process_organization_signup_messaging.delay(user_id=user.pk, organization_id=str(self._organization.id))

        if plan:
            OrganizationBilling.objects.create(
                organization=self._organization, plan=plan, should_setup_billing=plan.default_should_setup_billing,
            )

        return user


class PlanSerializer(ReadOnlySerializer):
    class Meta:
        model = Plan
        fields = [
            "key",
            "name",
            "custom_setup_billing_message",
            "allowance",
            "image_url",
            "self_serve",
            "is_metered_billing",
            "price_string",
        ]


class BillingSubscribeSerializer(serializers.Serializer):
    """
    Serializer allowing a user to set up billing information.
    """

    plan = serializers.SlugRelatedField(
        slug_field="key", queryset=Plan.objects.filter(is_active=True, self_serve=True),
    )

    def create(self, validated_data: Dict[str, Any]) -> Dict:

        assert self.context, "context is required"

        user: User = self.context["request"].user

        instance, _ = OrganizationBilling.objects.get_or_create(organization=user.organization,)

        if instance.is_billing_active:
            raise serializers.ValidationError(
                "Your organization already has billing set up, please contact us to change.",
            )

        instance.plan = validated_data["plan"]

        try:
            (checkout_session, customer_id) = instance.create_checkout_session(
                user=user, base_url=self.context["request"].build_absolute_uri("/"),
            )
        except ImproperlyConfigured as e:
            capture_exception(e)
            checkout_session = None

        if not checkout_session:
            raise serializers.ValidationError("Error starting your billing subscription. Please try again.",)

        instance.stripe_customer_id = customer_id
        instance.stripe_checkout_session = checkout_session
        instance.checkout_session_created_at = timezone.now()
        instance.should_setup_billing = True
        instance.save()

        return {
            "stripe_checkout_session": checkout_session,
            "subscription_url": f"/billing/setup?session_id={checkout_session}",
        }

    def to_representation(self, instance):
        return instance

