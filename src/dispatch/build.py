"""
Build one Dispatch from a template, a record and open gold, without sending it.

The steps run in this order:

  1. Read the scope (jurisdiction, state) and data range from the property values.
  2. Work out as_of and the windows.
  3. Build each section in template order, each with its own compiled filter.
  4. Render the browser copy (images as base64) and, once the browser link is
     known, the email copy (images by Content-ID). Inline CSS on both.
  5. Write the plain-text part and the subject.

`run.py` calls these steps around archiving and sending. `publish_templates.py`
calls them against the test fixtures to catch layout and partial errors.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from dispatch.config import TEST_SUBJECT_PREFIX
from dispatch.data.as_of import compute_data_dates
from dispatch.data.reference import ReferenceData
from dispatch.filters.compile import compile_filters
from dispatch.formatting import format_date_range, format_long_date, jurisdiction_label, parse_iso_date
from dispatch.render.inline import inline_css
from dispatch.render.layout import (
    BROWSER_MODE,
    EMAIL_MODE,
    partial_directories_for,
    render_layout,
    rendered_sections,
)
from dispatch.sections.base import SectionContext


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The window the footer and subject quote, in days
HEADLINE_WINDOW_DAYS = 7

# Where the figures come from, said once in every footer
DATA_SOURCE_SENTENCE = (
    'Source: Meta Ad Library and Google Ads Transparency Center, collected by AdVance. '
    'All figures are estimates, apportioned by audience.'
)


# ---------------------------------------------------------------- #
# Results
# ---------------------------------------------------------------- #

@dataclass
class BuiltSection:
    """One section after building: its config, its type module and what it returned."""
    config: Any
    module: Any
    result: Any


@dataclass
class DispatchScope:
    """The hard scope and data range a record's property values set."""
    jurisdiction: str
    state: Optional[str]
    start_date: Any
    end_date: Any


@dataclass
class BuiltDispatch:
    """Everything built for one Dispatch, before rendering."""
    template: Any
    record: Any
    property_values: dict
    scope: DispatchScope
    dates: Any
    sections: list = field(default_factory=list)

    @property
    def images(self):
        """Every chart image across all sections, as (content id, ChartImage) pairs in order."""
        pairs = []
        for built in self.sections:
            for image in built.result.images:
                pairs.append((image.content_id(built.config.id), image))
        return pairs


@dataclass
class RenderedDispatch:
    """The finished email: subject, both HTML renders and the plain-text part."""
    subject: str
    email_html: str
    browser_html: str
    plain_text: str


# ---------------------------------------------------------------- #
# Step 1: scope
# ---------------------------------------------------------------- #

def read_scope(property_values):
    """Read the jurisdiction, state and data range every Dispatch needs from the property values."""
    missing = []
    for key in ('jurisdiction', 'start_date', 'end_date'):
        if key not in property_values:
            missing.append(key)
    if missing:
        raise ValueError(f'a Dispatch needs these properties: {", ".join(missing)}')

    # The state applies only when the record supplied one
    state = property_values.get('state')
    return DispatchScope(
        jurisdiction=property_values['jurisdiction'],
        state=state,
        start_date=parse_iso_date(property_values['start_date']),
        end_date=parse_iso_date(property_values['end_date']),
    )


# ---------------------------------------------------------------- #
# Steps 2 and 3: dates and sections
# ---------------------------------------------------------------- #

def build_section(section_config, template, record, property_values, scope, dates, connection, reference):
    """Build one section with the template's global filters and its own compiled together."""
    section_module = section_config.section_type()
    params = section_config.parsed_params()

    # Globals first, then the section's own rules, so the section can only narrow
    compiled = compile_filters(
        [template.globals, section_config.filter_set()],
        reference.affiliation_group,
    )

    context = SectionContext(
        connection=connection,
        record=record,
        template=template,
        section=section_config,
        property_values=property_values,
        jurisdiction=scope.jurisdiction,
        state=scope.state,
        dates=dates,
        reference=reference,
        filter_sql=compiled.sql,
        filter_parameters=compiled.parameters,
    )
    result = section_module.build(context, params)
    return BuiltSection(config=section_config, module=section_module, result=result)


def build_dispatch(template, record, property_values, connection, reference=None, pinned_as_of=None):
    """
    Build every section of a Dispatch against open gold. A section that raises fails the build.

    A pinned as_of caps the one read from gold, so a rerun of a slot matches its first attempt.
    """
    scope = read_scope(property_values)
    dates = compute_data_dates(connection, scope.start_date, scope.end_date, pinned_as_of)

    # Reference data is read once and shared by every section
    if reference is None:
        reference = ReferenceData.load(connection)

    built = BuiltDispatch(
        template=template,
        record=record,
        property_values=property_values,
        scope=scope,
        dates=dates,
    )

    for section_config in template.sections:
        built_section = build_section(
            section_config, template, record, property_values, scope, dates, connection, reference,
        )
        built.sections.append(built_section)
    return built


# ---------------------------------------------------------------- #
# Steps 4 and 5: rendering
# ---------------------------------------------------------------- #

def subject_values(built):
    """The values every subject placeholder can take for this Dispatch."""
    headline_window = built.dates.window(HEADLINE_WINDOW_DAYS)
    return {
        'jurisdiction_label': jurisdiction_label(built.scope.jurisdiction, built.scope.state),
        'as_of_long': format_long_date(built.dates.as_of),
        'window_start_long': format_long_date(headline_window.start),
        'template_name': built.template.name,
        'record_name': built.record.name,
    }


def make_subject(built, is_test):
    """The subject line from the template, with the test prefix on a test send."""
    subject = built.template.format_subject(subject_values(built))
    if is_test:
        return TEST_SUBJECT_PREFIX + subject
    return subject


def dispatch_variables(built, mode, subject, browser_url, is_test):
    """The dispatch-wide variables a layout sees as `dispatch`."""
    headline_window = built.dates.window(HEADLINE_WINDOW_DAYS)

    # The Google callout, when Google stops before the window end
    callouts = []
    google_callout = built.dates.google_callout
    if google_callout is not None:
        callouts.append(google_callout)

    return {
        'mode': mode,
        'subject': subject,
        'is_test': is_test,
        'template_name': built.template.name,
        'record_name': built.record.name,
        'jurisdiction': built.scope.jurisdiction,
        'state': built.scope.state,
        'jurisdiction_label': jurisdiction_label(built.scope.jurisdiction, built.scope.state),
        'as_of': built.dates.as_of,
        'as_of_long': format_long_date(built.dates.as_of),
        'start_date': built.dates.start_date,
        'end_date': built.dates.end_date,
        'window_end': built.dates.window_end,
        'window_sentence': headline_window.sentence,
        'window_start': headline_window.start,
        'window_range': format_date_range(headline_window.start, headline_window.end),
        'data_source_sentence': DATA_SOURCE_SENTENCE,
        'callouts': callouts,
        'contact_email': built.record.contact(),
        'browser_url': browser_url,
        'property_values': built.property_values,
    }


def render_html(built, layout_text, mode, subject, browser_url, is_test):
    """Render the layout in one mode and inline its CSS."""
    variables = dispatch_variables(built, mode, subject, browser_url, is_test)
    sections = rendered_sections(built.sections, mode)
    partial_directories = partial_directories_for(built.sections)
    html = render_layout(layout_text, variables, sections, partial_directories)
    return inline_css(html)


def render_browser_html(built, layout_text, is_test):
    """The browser copy: images embedded as base64, no "view in browser" line."""
    subject = make_subject(built, is_test)
    return render_html(built, layout_text, BROWSER_MODE, subject, '', is_test)


def render_email_html(built, layout_text, browser_url, is_test):
    """The email copy: images by Content-ID, opening with the browser link."""
    subject = make_subject(built, is_test)
    return render_html(built, layout_text, EMAIL_MODE, subject, browser_url, is_test)


def plain_text(built, browser_url, is_test):
    """The plain-text part: headline figures from each section, the window sentence and the browser link."""
    subject = make_subject(built, is_test)
    headline_window = built.dates.window(HEADLINE_WINDOW_DAYS)
    lines = [subject, '']

    # Each section's own summary lines, in template order
    for built_section in built.sections:
        if not built_section.result.summary_lines:
            continue
        for line in built_section.result.summary_lines:
            lines.append(line)
        lines.append('')

    # The Google callout, the window, the link and the unsubscribe contact
    google_callout = built.dates.google_callout
    if google_callout is not None:
        lines.append(google_callout)
    lines.append(f'{headline_window.sentence}.')
    lines.append('')
    lines.append(f'View this email in your browser: {browser_url}')
    lines.append('')
    lines.append(f'To stop receiving these emails, contact {built.record.contact()}.')
    return '\n'.join(lines) + '\n'


def render_dispatch(built, layout_text, browser_url, is_test):
    """Render the email copy, the browser copy and the plain text for a built Dispatch."""
    return RenderedDispatch(
        subject=make_subject(built, is_test),
        email_html=render_email_html(built, layout_text, browser_url, is_test),
        browser_html=render_browser_html(built, layout_text, is_test),
        plain_text=plain_text(built, browser_url, is_test),
    )
