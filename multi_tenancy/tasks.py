import datetime
from typing import Optional

import dateutil
import posthoganalytics
from django.utils import timezone
from posthog.celery import app
from posthog.models import Organization

from multi_tenancy.stripe import report_subscription_item_usage
from multi_tenancy.utils import get_event_usage_for_timerange

from .models import OrganizationBilling


def compute_daily_usage_for_organizations(for_date: Optional[datetime.datetime] = None,) -> None:
    """
    Creates a separate async task to calculate the daily usage for each organization the day before.
    """

    for instance in OrganizationBilling.objects.filter(plan__is_metered_billing=True).exclude(
        stripe_subscription_item_id=""
    ):
        _compute_daily_usage_for_organization.delay(
            organization_billing_pk=str(instance.pk), for_date=for_date,
        )


@app.task(bind=True, ignore_result=True, max_retries=3)
def _compute_daily_usage_for_organization(self, organization_billing_pk: str, for_date: Optional[str]) -> None:

    target_date = (
        dateutil.parser.parse(for_date)
        if for_date
        else timezone.now() - datetime.timedelta(days=1)  # by default we do the day before
    )

    instance = OrganizationBilling.objects.get(pk=organization_billing_pk)
    start_time = datetime.datetime.combine(target_date, datetime.time.min)
    end_time = datetime.datetime.combine(target_date, datetime.time.max)
    event_usage = get_event_usage_for_timerange(
        organization=instance.organization, start_time=start_time, end_time=end_time
    )

    if event_usage is None:
        # Clickhouse not available, retry
        raise self.retry()

    report_monthly_usage.delay(
        subscription_item_id=instance.stripe_subscription_item_id, billed_usage=event_usage, for_date=start_time,
    )


@app.task(bind=True, ignore_result=True, max_retries=3)
def report_monthly_usage(self, subscription_item_id: str, billed_usage: int, for_date: str) -> None:

    success = report_subscription_item_usage(
        subscription_item_id=subscription_item_id, billed_usage=billed_usage, timestamp=dateutil.parser.parse(for_date),
    )

    if not success:
        raise self.retry()


@app.task(ignore_result=True, max_retries=3)
def report_invoice_payment_succeeded(organization_id: str, initial: bool) -> None:

    organization = Organization.objects.get(id=organization_id)
    payload = {
        "plan_key": organization.billing.get_plan_key(only_active=False),
        "billing_period_ends": organization.billing.billing_period_ends,
        "organization_id": str(organization.id),
    }
    event = "billing subscription activated" if initial else "billing subscription paid"

    for user in organization.members.all():
        posthoganalytics.capture(
            user.distinct_id, event, payload,
        )


@app.task(ignore_result=True, max_retries=3)
def report_card_validated(organization_id: str) -> None:

    organization = Organization.objects.get(id=organization_id)
    payload = {
        "plan_key": organization.billing.get_plan_key(only_active=False),
        "billing_period_ends": organization.billing.billing_period_ends,
        "organization_id": str(organization.id),
    }

    for user in organization.members.all():
        posthoganalytics.capture(
            user.distinct_id, "billing card validated", payload,
        )
