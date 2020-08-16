from django.contrib import admin

from .models import (
    TeamBilling,
)

@admin.register(TeamBilling)
class TeamBillingAdmin(admin.ModelAdmin):
    readonly_fields = ("stripe_checkout_session",)
    list_display = (
        "get_team_name",
        "stripe_customer_id",
        "should_setup_billing",
        "billing_period_ends",
        "price_id",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("should_setup_billing")

    def get_team_name(self, obj):
        return obj.team.name