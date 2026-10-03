"""
How figures and dates are written in a Dispatch.

Every section, the subject line and the footer format through these, so the
same amount reads the same way everywhere in an email. Each function is also
registered as a Jinja2 filter of the same name (see `render/layout.py`).
"""

import datetime


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# Month names, so a date never depends on the container's locale
MONTH_NAMES = (
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
)

# Amounts at or above these thresholds are written short, as in "$1.2m" or "$45k"
MILLION = 1_000_000
THOUSAND = 1_000


# ---------------------------------------------------------------- #
# Money
# ---------------------------------------------------------------- #

def format_money(amount):
    """Write an amount in whole dollars with thousands separators, as in "$4,487"."""
    if amount is None:
        return '$0'

    # Round to whole dollars, keeping the sign in front of the dollar sign
    rounded = int(round(float(amount)))
    if rounded < 0:
        return f'-${abs(rounded):,}'
    return f'${rounded:,}'


def format_money_short(amount):
    """Write an amount compactly for chart labels, as in "$1.2m", "$45k" or "$800"."""
    if amount is None:
        return '$0'

    value = float(amount)
    magnitude = abs(value)

    # Millions take one decimal place
    if magnitude >= MILLION:
        return f'${value / MILLION:.1f}m'

    # Thousands are whole
    if magnitude >= THOUSAND:
        return f'${value / THOUSAND:.0f}k'

    return format_money(value)


# ---------------------------------------------------------------- #
# Shares
# ---------------------------------------------------------------- #

def format_percent(share):
    """Write a share between 0 and 1 as a whole percentage, as in "42%"."""
    if share is None:
        return '0%'
    percentage = float(share) * 100
    return f'{percentage:.0f}%'


def safe_share(part, whole):
    """Return part divided by whole, or 0 when the whole is zero or missing."""
    if not whole:
        return 0.0
    return float(part) / float(whole)


# ---------------------------------------------------------------- #
# Dates
# ---------------------------------------------------------------- #

def format_long_date(day):
    """Write a date in full, as in "1 October 2026"."""
    month_name = MONTH_NAMES[day.month - 1]
    return f'{day.day} {month_name} {day.year}'


def format_day_month(day):
    """Write a date without its year, as in "25 September"."""
    month_name = MONTH_NAMES[day.month - 1]
    return f'{day.day} {month_name}'


def format_short_date(day):
    """Write a date briefly for chart axes, as in "25 Sep"."""
    month_name = MONTH_NAMES[day.month - 1]
    return f'{day.day} {month_name[:3]}'


def format_date_range(start, end):
    """Write an inclusive date range, dropping the first year when both share it."""
    same_year = start.year == end.year
    if same_year:
        return f'{format_day_month(start)} to {format_long_date(end)}'
    return f'{format_long_date(start)} to {format_long_date(end)}'


def window_sentence(window_days, start, end):
    """The sentence quoting a window, as in "Figures reflect the 7-day window 25 September to 1 October 2026"."""
    date_range = format_date_range(start, end)
    return f'Figures reflect the {window_days}-day window {date_range}'


# ---------------------------------------------------------------- #
# Jurisdictions
# ---------------------------------------------------------------- #

# The adjective each state takes in a subject line, as in "Victorian state"
STATE_ADJECTIVES = {
    'NSW': 'New South Wales',
    'VIC': 'Victorian',
    'QLD': 'Queensland',
    'WA': 'Western Australian',
    'SA': 'South Australian',
    'TAS': 'Tasmanian',
    'ACT': 'ACT',
    'NT': 'Northern Territory',
}


def jurisdiction_label(jurisdiction, state):
    """Name a record's jurisdiction for people, as in "Victorian state" or "Federal"."""
    if jurisdiction == 'federal':
        return 'Federal'

    # A state jurisdiction reads with its state's adjective
    adjective = STATE_ADJECTIVES.get(state)
    if adjective is None:
        adjective = str(state)
    return f'{adjective} state'


# ---------------------------------------------------------------- #
# Parsing
# ---------------------------------------------------------------- #

def parse_iso_date(text):
    """Read a `YYYY-MM-DD` string as a date, passing a date through unchanged."""
    if isinstance(text, datetime.datetime):
        return text.date()
    if isinstance(text, datetime.date):
        return text
    return datetime.date.fromisoformat(str(text))
