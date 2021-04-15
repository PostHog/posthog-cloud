from django.contrib import admin
from django.utils.safestring import mark_safe

from .models import OrganizationBilling, Plan


@admin.register(OrganizationBilling)
class OrganizationBillingAdmin(admin.ModelAdmin):
    search_fields = (
        "organization__name",
        "organization__members__email",
        "stripe_customer_id",
        "stripe_checkout_session",
        "stripe_subscription_item_id",
    )
    list_display = (
        "get_organization_name",
        "stripe_customer_id",
        "should_setup_billing",
        "billing_period_ends",
        "plan",
    )
    fields = (
        "organization",
        "stripe_customer_id",
        "stripe_subscription_id",
        "stripe_checkout_session",
        "plan",
        "should_setup_billing",
        "billing_period_ends",
        "is_billing_active",
        "event_allocation",
        "billing_docs",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("should_setup_billing")

    def get_organization_name(self, obj):
        return obj.organization.name

    def billing_docs(self, *args, **kwargs) -> str:
        return mark_safe(
            "When changing this object, remember to read"
            '<a href="https://posthog.com/handbook/growth/sales/billing#updating-subscriptions">'
            "our internal docs →</a>",
        )


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "name",
        "price_id",
        "is_active",
        "self_serve",
        "event_allowance",
        "price_string",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("key")
