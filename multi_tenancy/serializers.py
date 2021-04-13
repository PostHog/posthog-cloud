from decimal import Decimal
from typing import Any, Dict, Optional

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from messaging.tasks import process_organization_signup_messaging
from posthog.api.organization import OrganizationSignupSerializer
from posthog.models import User
from rest_framework import serializers
from sentry_sdk import capture_exception

from multi_tenancy.stripe import get_current_usage_bill

from .models import OrganizationBilling, Plan
from .utils import get_cached_monthly_event_usage


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
            "event_allowance",
            "image_url",
            "self_serve",
            "is_metered_billing",
            "price_string",
        ]


class BillingSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    current_usage = serializers.SerializerMethodField()
    subscription_url = serializers.SerializerMethodField()
    current_bill_amount = serializers.SerializerMethodField()
    should_display_current_bill = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationBilling
        fields = [
            "should_setup_billing",
            "is_billing_active",
            "plan",
            "billing_period_ends",
            "event_allocation",
            "current_usage",
            "subscription_url",
            "current_bill_amount",
            "should_display_current_bill",
        ]

    def get_current_usage(self, instance: OrganizationBilling) -> Optional[int]:
        try:
            return get_cached_monthly_event_usage(instance.organization)
        except Exception as e:
            capture_exception(e)
        return None

    def get_subscription_url(self, instance: OrganizationBilling) -> Optional[str]:
        request = self.context["request"]
        checkout_session = None
        if instance.should_setup_billing and not instance.is_billing_active:
            if (
                instance.stripe_checkout_session
                and instance.checkout_session_created_at
                and instance.checkout_session_created_at + timezone.timedelta(minutes=1439) > timezone.now()
            ):
                # Checkout session has been created and is still active (i.e. created less than 24 hours ago)
                checkout_session = instance.stripe_checkout_session
            else:
                try:
                    (checkout_session, customer_id) = instance.create_checkout_session(
                        user=request.user, base_url=request.build_absolute_uri("/"),
                    )
                except ImproperlyConfigured as e:
                    capture_exception(e)
                else:
                    if checkout_session:
                        OrganizationBilling.objects.filter(pk=instance.pk).update(
                            stripe_checkout_session=checkout_session,
                            stripe_customer_id=customer_id,
                            checkout_session_created_at=timezone.now(),
                        )

        return f"/billing/setup?session_id={checkout_session}" if checkout_session else None

    def get_should_display_current_bill(self, instance: OrganizationBilling) -> bool:
        if instance.is_billing_active and instance.plan.is_metered_billing:
            return True
        return False

    def get_current_bill_amount(self, instance: OrganizationBilling) -> Optional[Decimal]:
        """
        If the subscription is metered (usage-based), we return the accrued bill amount (in $) for the
        upcoming not-yet-billed invoice (i.e. usage of the current bill period).
        """
        if not instance.is_billing_active or not instance.plan.is_metered_billing:
            return None
        return get_current_usage_bill(instance.stripe_subscription_id)


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
