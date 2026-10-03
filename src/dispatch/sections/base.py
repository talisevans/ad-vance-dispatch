"""
The contract every section type keeps, and the context it is built with.

A section type is one folder, `dispatch/sections/<type>/`, holding one Python
module and one Jinja2 partial. The module exposes:

    TYPE_NAME    the type name templates use, e.g. "bias_gauge"
    Params       a pydantic model for the section's params
    DESCRIPTION  what the section is for, for the catalogue
    RENDERS      a one-line summary of what it draws, for the catalogue
    PARTIAL      the partial's file name, e.g. "bias_gauge.html.j2"
    build(context, params) -> SectionResult

`build` receives a `SectionContext` with the DuckDB connection, the record,
the dates, the reference data and the combined filter (template globals plus
the section's own) already compiled. It returns template variables, chart
images and footnotes. It never sends, uploads or writes anything.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from dispatch.data.as_of import DataDates
from dispatch.data.reference import ReferenceData


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The classification bias views always drop (decision D17)
GOVERNMENT_CLASSIFICATION = 'government'

# Finds each `$name` parameter a SQL statement refers to
PARAMETER_REFERENCE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)')

# The advert columns every spend-row subquery carries alongside the money
ADVERT_COLUMNS = (
    'datasource',
    'approach',
    'themes',
    'creator_id',
    'creator_name',
    'creator_classification',
    'creator_affiliation_id',
    'creator_affiliation',
    'creator_affiliation_bias',
    'is_local_government_content',
)


# ---------------------------------------------------------------- #
# What a section returns
# ---------------------------------------------------------------- #

@dataclass
class ChartImage:
    """One chart: its name within the section, its PNG bytes, how wide to show it and its alt text."""
    name: str
    png: bytes
    display_width: int
    display_height: int
    alt: str

    def content_id(self, section_id):
        """The Content-ID this image is attached under, unique across the email."""
        return f'{section_id}-{self.name}'


@dataclass
class SectionResult:
    """
    What a section returns: template variables, chart images, footnotes and plain-text lines.

    `notes` print under the section. `scope_notes` say what the section's figures always leave
    out; they print once in the email footer, with duplicates across sections removed.
    """
    variables: dict = field(default_factory=dict)
    images: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    summary_lines: list = field(default_factory=list)
    scope_notes: list = field(default_factory=list)


class SectionModule(Protocol):
    """The attributes every section type module exposes."""
    TYPE_NAME: str
    DESCRIPTION: str
    RENDERS: str
    PARTIAL: str
    Params: Any

    def build(self, context, params):
        """Build the section from its context and validated params."""


# ---------------------------------------------------------------- #
# What a section is built with
# ---------------------------------------------------------------- #

@dataclass
class SectionContext:
    """Everything a section needs: DuckDB connection, record, filters, dates and reference data."""

    # The open gold connection, with every gold, apportioned and lookup view mounted
    connection: Any

    # The record being sent, its template, and this section's own config
    record: Any
    template: Any
    section: Any

    # The record's validated property values
    property_values: dict

    # The hard scope: "federal" or "state", and the state code or None
    jurisdiction: str
    state: Optional[str]

    # as_of, the record's data range, the window end and Google's latest day
    dates: DataDates

    # Biases, affiliations, creators, colours and merges
    reference: ReferenceData

    # The combined filter (globals AND section) over the alias `adverts`, and its parameters
    filter_sql: str
    filter_parameters: dict

    # ------------------------------------------------------------ #
    # Dates
    # ------------------------------------------------------------ #

    @property
    def as_of(self):
        """The latest Meta date in gold."""
        return self.dates.as_of

    @property
    def start_date(self):
        """The record's `start_date`: where cumulative charts begin."""
        return self.dates.start_date

    @property
    def end_date(self):
        """The record's `end_date`."""
        return self.dates.end_date

    @property
    def window_end(self):
        """The last day of every window: the earlier of as_of and end_date."""
        return self.dates.window_end

    def window(self, days):
        """The N-day window ending at the window end, as a DateWindow with start, end and sentence."""
        return self.dates.window(days)

    # ------------------------------------------------------------ #
    # Parameters and queries
    # ------------------------------------------------------------ #

    def scope_parameters(self):
        """The parameters the scope subqueries bind: `$jurisdiction` and `$state`."""
        return {'jurisdiction': self.jurisdiction, 'state': self.state}

    def all_parameters(self, extra=None):
        """Every parameter a section query may use: the filter's, the scope's, then the caller's."""
        parameters = {}
        parameters.update(self.filter_parameters)
        parameters.update(self.scope_parameters())
        if extra:
            parameters.update(extra)
        return parameters

    def query(self, sql, parameters=None):
        """
        Run a query and return its rows as dictionaries.

        Binds the filter parameters, `$jurisdiction`, `$state` and any extra
        parameters given, passing only the ones the SQL refers to (DuckDB
        refuses unused parameters).
        """
        available = self.all_parameters(parameters)
        bound = bind_referenced(sql, available)
        cursor = self.connection.execute(sql, bound)

        column_names = []
        for description in cursor.description:
            column_names.append(description[0])

        rows = []
        for values in cursor.fetchall():
            rows.append(dict(zip(column_names, values)))
        return rows

    # ------------------------------------------------------------ #
    # Scoped spend rows
    # ------------------------------------------------------------ #

    def statewide_spend_sql(self):
        """
        A subquery of apportioned spend rows for the record's whole scope, filter applied.

        Columns: ad_key, date, spend, and the advert columns in ADVERT_COLUMNS.
        A state record, or a federal record with a state, reads `ad_state_daily`
        for that state. A federal record with no state reads national `ad_daily`.
        The jurisdiction hard filter is always applied first.
        """
        advert_columns = advert_column_list()

        # Choose the spend source: one state's share, or the national total
        if self.state is None:
            spend_source = (
                '(SELECT ad_key, date, jurisdiction, year, spend_avg AS spend FROM ad_daily)'
            )
            state_clause = ''
        else:
            spend_source = 'ad_state_daily'
            state_clause = '\n  AND spend_rows.state = $state'

        return (
            f'SELECT spend_rows.ad_key, spend_rows.date, spend_rows.spend, {advert_columns}\n'
            f'FROM {spend_source} AS spend_rows\n'
            f'JOIN adverts ON adverts.ad_key = spend_rows.ad_key AND adverts.year = spend_rows.year\n'
            f'WHERE spend_rows.jurisdiction = $jurisdiction{state_clause}\n'
            f'  AND ({self.filter_sql})'
        )

    def seat_spend_sql(self):
        """
        A subquery of apportioned spend rows per seat in the record's scope, filter applied.

        Columns: ad_key, date, spend, unique_electorate_id, electorate_name,
        electorate_state, and the advert columns in ADVERT_COLUMNS. Seats are
        those of the record's jurisdiction, narrowed to its state when set.
        """
        advert_columns = advert_column_list()

        # Narrow to the record's state when it has one
        state_clause = ''
        if self.state is not None:
            state_clause = '\n  AND electorates.state = $state'

        return (
            f'SELECT spend_rows.ad_key, spend_rows.date, spend_rows.spend,\n'
            f'       spend_rows.unique_electorate_id, electorates.electorate_name,\n'
            f'       electorates.state AS electorate_state, {advert_columns}\n'
            f'FROM ad_geo_daily AS spend_rows\n'
            f'JOIN electorates ON electorates.unique_electorate_id = spend_rows.unique_electorate_id\n'
            f'JOIN adverts ON adverts.ad_key = spend_rows.ad_key AND adverts.year = spend_rows.year\n'
            f'WHERE spend_rows.jurisdiction = $jurisdiction\n'
            f'  AND electorates.jurisdiction = $jurisdiction{state_clause}\n'
            f'  AND ({self.filter_sql})'
        )


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

def advert_column_list():
    """The advert columns as `adverts.<column>`, joined by commas."""
    qualified = []
    for column in ADVERT_COLUMNS:
        qualified.append(f'adverts.{column}')
    return ', '.join(qualified)


def bind_referenced(sql, available):
    """Keep only the parameters a SQL statement refers to, failing on any it lacks."""
    bound = {}
    for match in PARAMETER_REFERENCE.finditer(sql):
        name = match.group(1)
        if name in bound:
            continue
        if name not in available:
            raise KeyError(f'query refers to ${name}, which no parameter supplies')
        bound[name] = available[name]
    return bound


# ---------------------------------------------------------------- #
# Scope notes
# ---------------------------------------------------------------- #



def excluded_by_globals(context, key, value):
    """Whether the template's global filters already exclude one value of a key."""
    excluded_values = context.template.globals.exclude.get(key, [])
    return value in excluded_values


def government_scope_notes(context, figures_name):
    """
    The footer line for a section that always drops government advertising, e.g. "Bias figures
    exclude government advertising." None when the template already excludes government.
    """
    if excluded_by_globals(context, 'classification', GOVERNMENT_CLASSIFICATION):
        return []
    return [f'{figures_name} exclude government advertising.']
