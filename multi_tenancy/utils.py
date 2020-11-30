import calendar
import datetime
from typing import Optional, Tuple

import pytz
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from ee.clickhouse.client import sync_execute
from posthog.models import Organization, Team

EVENT_USAGE_CACHING_TTL: int = settings.EVENT_USAGE_CACHING_TTL


def get_monthly_event_usage(
    organization: Organization, at_date: datetime.datetime = None,
) -> Optional[int]:
    """
    Returns the number of events used in the calendar month (UTC) of the date provided for all
    teams of the organization. Intended mainly for billing purposes.
    """
    if not at_date:
        at_date = timezone.now()

    date_range: Tuple[int] = calendar.monthrange(at_date.year, at_date.month)
    start_date: datetime.datetime = datetime.datetime.combine(
        datetime.datetime(at_date.year, at_date.month, 1), datetime.time.min,
    ).replace(tzinfo=pytz.UTC)
    end_date: datetime.datetime = datetime.datetime.combine(
        datetime.datetime(at_date.year, at_date.month, date_range[1]),
        datetime.time.max,
    ).replace(tzinfo=pytz.UTC)

    result = sync_execute(
        "SELECT count(1) FROM events where team_id IN %(team_ids)s AND timestamp"
        " >= %(date_from)s AND timestamp <= %(date_to)s",
        {
            "date_from": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            "date_to": end_date.strftime("%Y-%m-%d %H:%M:%S"),
            "team_ids": list(
                Team.objects.filter(organization=organization).values_list(
                    "id", flat=True,
                ),
            ),
        },
    )

    if result:
        return result[0][0]

    return None  # in case CH is not available (mainly to run posthog tests)


def get_cached_monthly_event_usage(organization: Organization) -> Optional[int]:
    """
    Returns the cached number of events used in the current calendar month. Results will be cached for 12 hours.
    """

    cache_key: str = f"monthly_usage_{organization.id}"
    cached_result: int = cache.get(cache_key)

    if cached_result is not None:
        return cached_result

    now: datetime.datetime = timezone.now()
    result: int = get_monthly_event_usage(organization=organization, at_date=now)

    if result is None:
        # Don't cache unavailable/error result
        return result

    # Cache the result
    start_of_next_month = datetime.datetime.combine(
        datetime.datetime(now.year, now.month, 1), datetime.time.min,
    ).replace(tzinfo=pytz.UTC) + relativedelta(months=+1)

    cache.set(
        cache_key,
        result,
        min(
            EVENT_USAGE_CACHING_TTL,
            (start_of_next_month - timezone.now()).total_seconds(),
        ),
    )  # cache result for default time or until next month

    return result
