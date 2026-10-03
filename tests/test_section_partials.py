"""
The four section partials rendered together through the real build and render
path: Outlook-safe markup, charts by Content-ID, bars as table cells, and the
federal branch rendering as well as the state one.
"""

import re

import pytest

from dispatch.build import build_dispatch, render_dispatch
from dispatch.delivery.message import build_message
from dispatch.models.record import DispatchRecord
from dispatch.models.template import Template
from tests.conftest import PROBE_LAYOUT_PATH, record_document


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

BROWSER_URL = 'https://storage.example.test/sent/r1/slot/browser.html?signature=abc'

# The em-dash, which must never appear in output
EM_DASH = chr(0x2014)

# The four section types laid out as the Weekly Campaign Brief lays them out
FOUR_SECTIONS = [
    {'id': 'statewide_spend', 'type': 'bias_gauge', 'params': {'window_days': 7}},
    {'id': 'cumulative', 'type': 'cumulative_spend', 'params': {'interval': 'week', 'top_affiliations': 3}},
    {'id': 'messaging', 'type': 'messaging_tone', 'params': {
        'window_days': 28,
        'top_themes': 5,
        'cards': [
            {'label': 'Labor', 'affiliation_ids': ['aff_labor']},
            {'label': 'Liberal', 'affiliation_ids': ['aff_liberal']},
            {'label': 'Greens', 'affiliation_ids': ['aff_greens']},
            {'label': 'Socialist Alliance', 'affiliation_ids': ['aff_socialist_alliance']},
            {'label': 'Teals', 'affiliation_ids': ['aff_climate_200']},
        ],
    }},
    {'id': 'top_seats', 'type': 'top_seats', 'params': {'limit': 10, 'windows': [7, 28], 'rank_by_window': 7},
     'include': {'classification': ['political participant']}},
]


def four_section_template():
    """A template using all four section types, with the probe layout."""
    return Template.model_validate({
        'id': 'four_sections',
        'schema_version': 1,
        'name': 'Four Section Brief',
        'description': 'All four section types.',
        'subject': '{jurisdiction_label} brief, week to {as_of_long}',
        'layout_path': 'templates/four_sections/layout.html.j2',
        'required_properties': [
            {'key': 'start_date', 'label': 'Data from', 'type': 'date'},
            {'key': 'end_date', 'label': 'Data to', 'type': 'date'},
            {'key': 'jurisdiction', 'label': 'Jurisdiction', 'type': 'enum', 'options': ['federal', 'state']},
            {'key': 'state', 'label': 'State', 'type': 'enum',
             'options': ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT'],
             'required_when': {'jurisdiction': 'state'}},
        ],
        'globals': {'include': {}, 'exclude': {'classification': ['government']}},
        'sections': FOUR_SECTIONS,
    })


def render_for(gold_connection, property_values):
    """Build and render the four-section template for one set of property values."""
    template = four_section_template()
    document = record_document(template_id='four_sections', property_values=property_values)
    document['id'] = 'r1'
    record = DispatchRecord.model_validate(document)
    values = template.validate_property_values(record.property_values)
    built = build_dispatch(template, record, values, gold_connection)

    with open(PROBE_LAYOUT_PATH, encoding='utf-8') as layout_file:
        layout_text = layout_file.read()
    return built, render_dispatch(built, layout_text, BROWSER_URL, False)


@pytest.fixture
def victorian(gold_connection):
    """The four sections rendered for the VIC state record."""
    return render_for(gold_connection, {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'state',
        'state': 'VIC',
    })


# ---------------------------------------------------------------- #
# Markup
# ---------------------------------------------------------------- #

def test_partials_are_outlook_safe(victorian):
    """No SVG, flexbox or grid, and no em-dash, in either render."""
    _built, output = victorian
    for html in (output.email_html, output.browser_html):
        assert '<svg' not in html
        assert 'display: flex' not in html
        assert 'display:flex' not in html
        assert 'display:grid' not in html
        assert 'display: grid' not in html
        assert EM_DASH not in html
    assert EM_DASH not in output.plain_text


def test_every_section_heading_renders_in_order(victorian):
    """The four headings appear in template order."""
    _built, output = victorian
    html = output.email_html
    positions = []
    for heading in ('Statewide spend', 'Cumulative spend', 'Messaging and tone', 'Top 10 seats by spend'):
        assert heading in html
        positions.append(html.index(heading))
    assert positions == sorted(positions)


def test_charts_referenced_by_content_id(victorian):
    """The gauge and both cumulative charts are referenced by their Content-IDs."""
    _built, output = victorian
    html = output.email_html
    assert 'src="cid:statewide_spend-gauge"' in html
    assert 'src="cid:cumulative-biases"' in html
    assert 'src="cid:cumulative-affiliations"' in html
    assert len(re.findall(r'src="cid:', html)) == 3


def test_message_attaches_the_three_charts(victorian):
    """The MIME message carries one inline PNG per chart."""
    built, output = victorian
    message, _message_id = build_message(output, built.images, 'reader@example.test', 'admin@example.test')
    content_ids = []
    for part in message.walk():
        if part.get_content_type() == 'image/png':
            content_ids.append(part['Content-ID'])
    assert sorted(content_ids) == [
        '<cumulative-affiliations>',
        '<cumulative-biases>',
        '<statewide_spend-gauge>',
    ]


def test_tone_and_theme_bars_are_table_cells(victorian):
    """The Liberal card's 80% negative tone is a table cell, not an image."""
    _built, output = victorian
    html = output.email_html
    assert 'width="80%" height="14" bgcolor="#d9822b"' in html
    assert 'No advertising in the last 28 days' in html


def test_figures_reach_the_html(victorian):
    """Hand-checked figures appear in the rendered email."""
    _built, output = victorian
    html = output.email_html
    assert '$4,165' in html
    assert '$1,715' in html
    assert '$8,370' in html
    assert '$2,450' in html
    assert 'Margin' not in html


def test_plain_text_carries_every_section(victorian):
    """Each section adds its headline lines to the plain-text part."""
    _built, output = victorian
    text = output.plain_text
    assert 'Statewide spend, 7 days: Left $1,470, Centre and unmapped $1,715, Right $980, total $4,165.' in text
    assert 'Cumulative spend since 1 August 2026: $18,880.' in text
    assert 'Liberal: $2,800, 20% compare and contrast, 80% negative.' in text
    assert '1. Kew: $2,450. Leader Climate 200 $1,050, runner-up Labor $560.' in text


# ---------------------------------------------------------------- #
# Other branches
# ---------------------------------------------------------------- #

def test_federal_branch_renders(gold_connection):
    """A national federal record renders all four sections too."""
    _built, output = render_for(gold_connection, {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'federal',
    })
    assert 'National spend' in output.email_html
    assert 'Top 10 seats by spend' in output.email_html


def test_new_south_wales_branch_renders(gold_connection):
    """The NSW state record (the publish dry run's sample) renders, with empty cards greyed."""
    _built, output = render_for(gold_connection, {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'state',
        'state': 'NSW',
    })
    assert 'Statewide spend' in output.email_html
    assert '$1,225' in output.email_html
