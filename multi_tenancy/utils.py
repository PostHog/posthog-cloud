import calendar
import datetime
from typing import Tuple

import pytz
from django.utils import timezone
from ee.clickhouse.client import sync_execute
from posthog.models import Event, Organization


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

    result = sync_execute(
        "SELECT count(1) FROM events where team_id IN %(team_ids)s AND timestamp"
        " >= %(date_from)s AND timestamp <= %(date_to)s",
        {
            "date_from": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            "date_to": end_date.strftime("%Y-%m-%d %H:%M:%S"),
            "team_ids": organization.teams.values_list("id", flat=True),
        },
    )

    return result[0][0]
