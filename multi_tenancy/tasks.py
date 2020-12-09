import datetime

from django.db import transaction
from django.utils import timezone
from posthog.celery import app

from multi_tenancy.stripe import report_subscription_item_usage

from .models import MonthlyBillingRecord, OrganizationBilling


def compute_monthly_usage_for_organizations(
    at_date: datetime.datetime = timezone.now(),
) -> None:
    """
    Creates a separate async task to calculate the monthly usage for each organization at the specified date.
    """

    for instance in OrganizationBilling.objects.all():
        compute_monthly_usage_for_organization.delay(
            organization_billing_id=instance.id, at_date=at_date
        )


@app.task(ignore_result=True, max_retries=3)
def compute_monthly_usage_for_organization(
    organization_billing_id: str, at_date: datetime.datetime = timezone.now()
) -> None:

    instance = OrganizationBilling.objects.get(id=organization_billing_id)
    report = instance.calculate_monthly_usage()

    if report:
        report_monthly_usage.delay(monthly_billing_record_id=report.id)


@app.task(ignore_result=True, max_retries=3)
def report_monthly_usage(monthly_billing_record_id: str,) -> None:
    instance = MonthlyBillingRecord.objects.get(id=monthly_billing_record_id)

    if instance.usage_reported:
        return

    with transaction.atomic():
        # Lock object (database-level) while report is being sent to Stripe
        instance = MonthlyBillingRecord.objects.select_for_update().get(id=instance.pk)

        success = report_subscription_item_usage(
            subscription_item_id=instance.organization_billing.stripe_subscription_item_id,
            billed_usage=instance.billed_usage,
            timestamp=datetime.datetime.combine(
                instance.billing_period, datetime.time.min
            ),
        )

        if success:
            instance.usage_reported = True
            instance.save()
