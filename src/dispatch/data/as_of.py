"""
The as_of date, the data windows that count back from it, and the Google
completeness check (decisions D7 and D16).

  1. `as_of` is the latest `ad_daily.date` for Meta adverts across the whole
     gold table. It never depends on the run date.
  2. The window end is the earlier of `as_of` and the record's `end_date`.
  3. An N-day window runs from `window_end - (N - 1)` to `window_end`, inclusive.
  4. When Google's latest date is before the window end, the email carries a
     callout saying Google is incomplete after that date.

Worked example on a 3 October 2026 run: Meta's latest date is 1 October, so
the 7-day window is 25 September to 1 October and the 28-day window is
4 September to 1 October.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from dispatch.formatting import format_long_date, window_sentence


# ---------------------------------------------------------------- #
# Queries
# ---------------------------------------------------------------- #

# The latest day of data for one datasource, across the whole gold table
LATEST_DATE_SQL = """
SELECT max(daily.date)
FROM ad_daily AS daily
JOIN adverts USING (ad_key)
WHERE adverts.datasource = $datasource
"""

META_DATASOURCE = 'meta'
GOOGLE_DATASOURCE = 'google'


def latest_date(connection, datasource):
    """The latest `ad_daily.date` for one datasource, or None when it has no rows."""
    cursor = connection.execute(LATEST_DATE_SQL, {'datasource': datasource})
    row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


# ---------------------------------------------------------------- #
# Windows
# ---------------------------------------------------------------- #

@dataclass(frozen=True)
class DateWindow:
    """An inclusive run of days ending at the window end."""
    days: int
    start: datetime.date
    end: datetime.date

    @property
    def sentence(self):
        """The sentence quoting this window, as in "Figures reflect the 7-day window ..."."""
        return window_sentence(self.days, self.start, self.end)


@dataclass(frozen=True)
class DataDates:
    """The dates a run reads data for: as_of, the record's range, and Google's latest day."""
    as_of: datetime.date
    start_date: datetime.date
    end_date: datetime.date
    google_latest: Optional[datetime.date]

    @property
    def window_end(self):
        """The last day of every window: the earlier of as_of and the record's end_date."""
        if self.end_date < self.as_of:
            return self.end_date
        return self.as_of

    def window(self, days):
        """The N-day window ending at the window end, both ends inclusive."""
        if days < 1:
            raise ValueError(f'a window needs at least one day, got {days}')
        start = self.window_end - datetime.timedelta(days=days - 1)
        return DateWindow(days=days, start=start, end=self.window_end)

    @property
    def google_incomplete(self):
        """Whether Google's data stops before the window end."""
        if self.google_latest is None:
            return True
        return self.google_latest < self.window_end

    @property
    def google_callout(self):
        """The callout text when Google is incomplete, otherwise None."""
        if not self.google_incomplete:
            return None
        if self.google_latest is None:
            return 'Google data is not available. Figures include Meta only.'
        latest_text = format_long_date(self.google_latest)
        return f'Google data is incomplete after {latest_text}. Figures for those days include Meta only.'


def compute_data_dates(connection, start_date, end_date, pinned_as_of=None):
    """
    Read as_of and Google's latest day from gold, and pair them with the record's range.

    A pinned as_of, from an earlier attempt at the same slot, caps the one read
    from gold, so a rerun quotes the same window as the first attempt.
    """
    as_of = latest_date(connection, META_DATASOURCE)
    if as_of is None:
        raise ValueError('gold holds no Meta rows, so as_of cannot be worked out')

    # Hold a rerun to the as_of its slot was first built with
    if pinned_as_of is not None:
        gold_is_newer = as_of > pinned_as_of
        if gold_is_newer:
            as_of = pinned_as_of

    google_latest = latest_date(connection, GOOGLE_DATASOURCE)
    return DataDates(
        as_of=as_of,
        start_date=start_date,
        end_date=end_date,
        google_latest=google_latest,
    )
