"""
Name the slot a run belongs to, so reruns of the same firing share a ledger.

  1. Scheduled: the most recent cron fire time at or before now, in the
     record's own timezone, written `YYYY-MM-DDTHH:MM`. A Scheduler retry five
     minutes later finds the same slot.
  2. Manual ("Send now"): `manual-<UTC timestamp>`, a fresh slot every time.
  3. Test sends have no slot.

Worked example: a weekly Monday 09:00 Melbourne record. Daylight saving starts
on Sunday 4 October 2026, so that Monday's 09:00 is 22:00 UTC on the Sunday,
where the Monday before it was 23:00 UTC. A run at 22:05 UTC on 4 October, or
its retry at 22:10, lands in slot `2026-10-05T09:00`.
"""

import datetime
import zoneinfo

from croniter import croniter


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# How a scheduled slot is written, in the record's local time
SLOT_FORMAT = '%Y-%m-%dT%H:%M'

# How a manual slot's UTC timestamp is written
MANUAL_STAMP_FORMAT = '%Y%m%dT%H%M%SZ'

# A nudge past the start of the current minute, so a fire time equal to now still counts
JUST_PAST_THE_MINUTE = datetime.timedelta(seconds=1)


# ---------------------------------------------------------------- #
# Slots
# ---------------------------------------------------------------- #

def scheduled_fire_time(cron, timezone_name, now):
    """The most recent fire time of a cron at or before an aware `now`, in the given timezone."""
    if now.tzinfo is None:
        raise ValueError('now must carry a timezone')

    local_now = now.astimezone(zoneinfo.ZoneInfo(timezone_name))

    # Search back from just after the start of this minute, so a fire time this minute is found
    minute_start = local_now.replace(second=0, microsecond=0)
    search_from = minute_start + JUST_PAST_THE_MINUTE
    schedule = croniter(cron, search_from)
    return schedule.get_prev(datetime.datetime)


def scheduled_slot(cron, timezone_name, now):
    """The scheduled slot name for a run at `now`, as in `2026-10-05T09:00`."""
    fire_time = scheduled_fire_time(cron, timezone_name, now)
    return fire_time.strftime(SLOT_FORMAT)


def manual_slot(now):
    """A fresh slot name for a "Send now" run, as in `manual-20261003T001500Z`."""
    now_utc = now.astimezone(datetime.timezone.utc)
    stamp = now_utc.strftime(MANUAL_STAMP_FORMAT)
    return f'manual-{stamp}'
