"""
Build a SectionContext over the fixture gold for section tests, and run a section in it.
"""

import datetime

from dispatch.data.as_of import compute_data_dates
from dispatch.filters.compile import compile_filters
from dispatch.models.template import FilterSet
from dispatch.sections.base import SectionContext


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The record range every fixture figure in tests/fixtures/README.md uses
FIXTURE_START_DATE = datetime.date(2026, 8, 1)
FIXTURE_END_DATE = datetime.date(2026, 11, 28)

# The Weekly Campaign Brief's global filter
NO_GOVERNMENT = FilterSet(exclude={'classification': ['government']})

# The Weekly Campaign Brief's Top Seats section filter
POLITICAL_PARTICIPANTS = FilterSet(include={'classification': ['political participant']})


# ---------------------------------------------------------------- #
# Contexts
# ---------------------------------------------------------------- #

def make_section_context(
    connection,
    reference,
    jurisdiction='state',
    state='VIC',
    filter_sets=(NO_GOVERNMENT,),
    start_date=FIXTURE_START_DATE,
    end_date=FIXTURE_END_DATE,
):
    """A SectionContext over the fixture gold for one scope, filter stack and record range."""
    compiled = compile_filters(list(filter_sets), reference.affiliation_group)
    dates = compute_data_dates(connection, start_date, end_date)
    return SectionContext(
        connection=connection,
        record=None,
        template=None,
        section=None,
        property_values={},
        jurisdiction=jurisdiction,
        state=state,
        dates=dates,
        reference=reference,
        filter_sql=compiled.sql,
        filter_parameters=compiled.parameters,
    )


def build_section(section_module, context, params=None):
    """Validate params through the section's own model and build it."""
    if params is None:
        params = {}
    parsed = section_module.Params.model_validate(params)
    return section_module.build(context, parsed)
