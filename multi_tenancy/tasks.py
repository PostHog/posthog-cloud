import datetime

import dateutil
from django.utils import timezone
from posthog.celery import app

from multi_tenancy.stripe import report_subscription_item_usage
from multi_tenancy.utils import get_event_usage_for_timerange

from .models import OrganizationBilling


def compute_daily_usage_for_organizations() -> None:
    """
    Creates a separate async task to calculate the monthly usage for each organization at the specified date.
    """

    for instance in OrganizationBilling.objects.all():
        _compute_daily_usage_for_organization.delay(
            organization_billing_pk=str(instance.pk)
        )


@app.task(bind=True, ignore_result=True, max_retries=3)
def _compute_daily_usage_for_organization(self, organization_billing_pk: str) -> None:

    instance = OrganizationBilling.objects.get(pk=organization_billing_pk)
    yesterday = timezone.now() - datetime.timedelta(days=1)
    start_time = datetime.datetime.combine(yesterday, datetime.time.min)
    end_time = datetime.datetime.combine(yesterday, datetime.time.max)
    event_usage = get_event_usage_for_timerange(
        organization=instance.organization, start_time=start_time, end_time=end_time
    )

    if event_usage < 0:
        # Clickhouse not available, retry
        raise self.retry()

    report_monthly_usage.delay(
        subscription_item_id=instance.stripe_subscription_item_id,
        billed_usage=event_usage,
        timestamp=start_time,
    )


@app.task(bind=True, ignore_result=True, max_retries=3)
def report_monthly_usage(
    self, subscription_item_id: str, billed_usage: int, timestamp: datetime.datetime
) -> None:

    success = report_subscription_item_usage(
        subscription_item_id=subscription_item_id,
        billed_usage=billed_usage,
        timestamp=dateutil.parser.parse(timestamp),
    )

    if not success:
        raise self.retry()
