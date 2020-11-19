from django.contrib import admin

from .models import OrganizationBilling, Plan


@admin.register(OrganizationBilling)
class OrganizationBillingAdmin(admin.ModelAdmin):
    readonly_fields = ("stripe_checkout_session",)
    search_fields = ('organization__name', 'organization__members__email')
    list_display = (
        "get_organization_name",
        "stripe_customer_id",
        "should_setup_billing",
        "billing_period_ends",
        "plan",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("should_setup_billing")

    def get_organization_name(self, obj):
        return obj.organization.name


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "name",
        "price_id",
        "is_active",
        "self_serve",
        "event_allowance",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("key")
