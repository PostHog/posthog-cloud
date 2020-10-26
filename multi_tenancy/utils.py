import calendar
import datetime
from typing import Tuple

import pytz
from django.core.cache import cache
from django.utils import timezone
from posthog.models import Event, Organization

EVENT_CACHING_EXPIRY: int = 43_200  # 12 hours


def get_monthly_event_usage(
    organization: Organization, at_date: datetime.datetime = None,
) -> int:
    """
    Returns the number of events used in the calendar month (UTC) of the date provided for all
    teams of the organization. Intended mainly for billing purposes.
    Example: instance.get_monthly_event_usage()
        => 584127
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

    return Event.objects.filter(
        team__in=organization.teams.all(),
        timestamp__gte=start_date,
        timestamp__lte=end_date,
    ).count()


def get_cached_monthly_event_usage(organization: Organization) -> int:
    """
    Returns the cached number of events used in the current calendar month. Results will be cached for 12 hours.
    """

    cache_key: str = f"monthly_usage_{organization.id}"
    cached_result: int = cache.get(cache_key)

    if cached_result:
        return cached_result

    now: datetime.datetime = timezone.now()
    result: int = get_monthly_event_usage(organization=organization, at_date=now)

    # Cache the result
    start_of_next_month = datetime.datetime.combine(
        datetime.datetime(now.year, now.month, 1), datetime.time.min,
    ).replace(tzinfo=pytz.UTC)
    cache.set(
        cache_key,
        result,
        min(
            EVENT_CACHING_EXPIRY,
            (start_of_next_month - timezone.now()).total_seconds(),
        ),
    )  # cache result for default time or until next month

    return result
