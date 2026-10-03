"""
Slot tests: weekly Monday slots across the Melbourne daylight saving change,
reruns landing in the same slot, daily slots, and manual slot names.
"""

import datetime

from dispatch.scheduling.slots import manual_slot, scheduled_slot


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

MELBOURNE = 'Australia/Melbourne'
WEEKLY_MONDAY_NINE = '0 9 * * 1'


def utc(text):
    """An aware UTC datetime from `YYYY-MM-DD HH:MM`."""
    naive = datetime.datetime.strptime(text, '%Y-%m-%d %H:%M')
    return naive.replace(tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------- #
# Scheduled slots
# ---------------------------------------------------------------- #

def test_weekly_monday_before_daylight_saving():
    """Monday 28 September 09:00 AEST is 23:00 UTC on the Sunday."""
    slot = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-09-27 23:00'))
    assert slot == '2026-09-28T09:00'


def test_weekly_monday_after_daylight_saving_starts():
    """Daylight saving starts 4 October, so Monday 5 October 09:00 AEDT is 22:00 UTC on the Sunday."""
    slot = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-10-04 22:00'))
    assert slot == '2026-10-05T09:00'


def test_run_just_before_the_fire_time_belongs_to_last_week():
    """At 21:59 UTC on 4 October it is 08:59 local, so the latest slot is the week before."""
    slot = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-10-04 21:59'))
    assert slot == '2026-09-28T09:00'


def test_rerun_finds_the_same_slot():
    """The Scheduler retry five minutes later, and a rerun an hour later, share the slot."""
    first = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-10-04 22:00'))
    retry = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-10-04 22:05'))
    later = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-10-04 23:05'))
    assert first == retry == later == '2026-10-05T09:00'


def test_daily_slot():
    """A daily 07:30 Perth schedule (no daylight saving) names today's slot after 07:30 local."""
    slot = scheduled_slot('30 7 * * *', 'Australia/Perth', utc('2026-10-04 23:45'))
    assert slot == '2026-10-05T07:30'


def test_daylight_saving_ends():
    """Daylight saving ends 5 April 2026, so Monday 6 April 09:00 AEST is 23:00 UTC on the Sunday."""
    slot = scheduled_slot(WEEKLY_MONDAY_NINE, MELBOURNE, utc('2026-04-05 23:00'))
    assert slot == '2026-04-06T09:00'


# ---------------------------------------------------------------- #
# Manual slots
# ---------------------------------------------------------------- #

def test_manual_slot_uses_utc():
    """A manual slot is named after the UTC moment it ran."""
    melbourne_time = utc('2026-10-04 22:15').astimezone(datetime.timezone(datetime.timedelta(hours=11)))
    assert manual_slot(melbourne_time) == 'manual-20261004T221500Z'
