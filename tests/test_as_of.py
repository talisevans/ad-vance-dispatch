"""
as_of tests: Meta's latest date wins, end_date caps the window, windows count
back inclusively, and the Google callout appears only when Google stops before
the window end.
"""

import datetime

import duckdb
import pytest

from dispatch.data.as_of import compute_data_dates


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

START = datetime.date(2026, 8, 1)
FAR_END = datetime.date(2026, 11, 28)


def day(text):
    """Read a `YYYY-MM-DD` string as a date."""
    return datetime.date.fromisoformat(text)


def tiny_gold(meta_last, google_last):
    """An in-memory gold with one Meta and one Google advert ending on the given days."""
    connection = duckdb.connect(':memory:')
    connection.execute('CREATE TABLE adverts (ad_key VARCHAR, datasource VARCHAR)')
    connection.execute("INSERT INTO adverts VALUES ('meta_1', 'meta'), ('google_1', 'google')")
    connection.execute('CREATE TABLE ad_daily (date DATE, ad_key VARCHAR)')
    connection.execute("INSERT INTO ad_daily VALUES ($day, 'meta_1')", {'day': meta_last})
    if google_last is not None:
        connection.execute("INSERT INTO ad_daily VALUES ($day, 'google_1')", {'day': google_last})
    return connection


# ---------------------------------------------------------------- #
# as_of
# ---------------------------------------------------------------- #

def test_meta_latest_date_wins_on_fixtures(gold_connection):
    """Google runs to 2 October in the fixtures, but as_of follows Meta to 1 October."""
    dates = compute_data_dates(gold_connection, START, FAR_END)
    assert dates.as_of == day('2026-10-01')
    assert dates.google_latest == day('2026-10-02')
    assert dates.window_end == day('2026-10-01')


def test_pinned_as_of_caps_a_newer_gold(gold_connection):
    """A rerun pinned to 30 September keeps that as_of although gold runs to 1 October."""
    dates = compute_data_dates(gold_connection, START, FAR_END, pinned_as_of=day('2026-09-30'))
    assert dates.as_of == day('2026-09-30')
    assert dates.window(7).start == day('2026-09-24')


def test_pinned_as_of_never_moves_as_of_forward(gold_connection):
    """A pin later than gold's latest Meta day leaves as_of at gold's day."""
    dates = compute_data_dates(gold_connection, START, FAR_END, pinned_as_of=day('2026-10-05'))
    assert dates.as_of == day('2026-10-01')


def test_worked_example_windows(gold_connection):
    """The plan's worked example: 7 days is 25 Sep to 1 Oct, 28 days is 4 Sep to 1 Oct."""
    dates = compute_data_dates(gold_connection, START, FAR_END)
    seven = dates.window(7)
    twenty_eight = dates.window(28)
    assert (seven.start, seven.end) == (day('2026-09-25'), day('2026-10-01'))
    assert (twenty_eight.start, twenty_eight.end) == (day('2026-09-04'), day('2026-10-01'))
    assert seven.sentence == 'Figures reflect the 7-day window 25 September to 1 October 2026'


def test_end_date_caps_the_window():
    """A record whose end_date is before as_of ends its windows on end_date."""
    connection = tiny_gold(day('2026-10-01'), day('2026-10-01'))
    dates = compute_data_dates(connection, START, day('2026-09-20'))
    assert dates.as_of == day('2026-10-01')
    assert dates.window_end == day('2026-09-20')
    assert dates.window(7).start == day('2026-09-14')


def test_window_rejects_zero_days():
    """A window needs at least one day."""
    connection = tiny_gold(day('2026-10-01'), day('2026-10-01'))
    dates = compute_data_dates(connection, START, FAR_END)
    with pytest.raises(ValueError):
        dates.window(0)


def test_no_meta_rows_is_an_error():
    """Without Meta rows there is no as_of, and the run must not guess one."""
    connection = duckdb.connect(':memory:')
    connection.execute('CREATE TABLE adverts (ad_key VARCHAR, datasource VARCHAR)')
    connection.execute('CREATE TABLE ad_daily (date DATE, ad_key VARCHAR)')
    with pytest.raises(ValueError):
        compute_data_dates(connection, START, FAR_END)


# ---------------------------------------------------------------- #
# The Google callout
# ---------------------------------------------------------------- #

def test_no_callout_when_google_reaches_the_window_end():
    """Google up to as_of means no callout."""
    connection = tiny_gold(day('2026-10-01'), day('2026-10-01'))
    dates = compute_data_dates(connection, START, FAR_END)
    assert dates.google_callout is None


def test_callout_when_google_stops_early():
    """Google stopping on 29 September, before a 1 October window end, raises the callout."""
    connection = tiny_gold(day('2026-10-01'), day('2026-09-29'))
    dates = compute_data_dates(connection, START, FAR_END)
    assert dates.google_callout == (
        'Google data is incomplete after 29 September 2026. Figures for those days include Meta only.'
    )


def test_no_callout_when_end_date_is_before_google_stops():
    """A window capped at 20 September is complete even though Google stops on 29 September."""
    connection = tiny_gold(day('2026-10-01'), day('2026-09-29'))
    dates = compute_data_dates(connection, START, day('2026-09-20'))
    assert dates.google_callout is None


def test_callout_when_google_has_no_rows():
    """No Google rows at all is also called out."""
    connection = tiny_gold(day('2026-10-01'), None)
    dates = compute_data_dates(connection, START, FAR_END)
    assert dates.google_callout == 'Google data is not available. Figures include Meta only.'
