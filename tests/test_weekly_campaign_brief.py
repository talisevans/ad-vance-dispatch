"""
The Weekly Campaign Brief end to end: the repository's template.json and
layout rendered against the fixtures, compared with a stored snapshot, checked
for Outlook-safe markup, and previewed to disk through the local render command.

To refresh the snapshots after a deliberate change to the layout, a partial or
the fixtures, run:

    DISPATCH_UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/test_weekly_campaign_brief.py

then read the diff before committing it.
"""

import os
import re

import pytest

from dispatch.build import build_dispatch, render_dispatch
from dispatch.main import main
from dispatch.models.record import DispatchRecord
from dispatch.publish_templates import TEMPLATES_DIRECTORY, load_template_source, publish
from tests.conftest import FIXTURE_GOLD_DIRECTORY, FIXTURE_LOOKUPS_DIRECTORY, record_document


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

TEMPLATE_ID = 'weekly_campaign_brief'
TEMPLATE_DIRECTORY = os.path.join(TEMPLATES_DIRECTORY, TEMPLATE_ID)
EXAMPLE_RECORD_PATH = os.path.join(TEMPLATE_DIRECTORY, 'example_record.json')

# The stored snapshots, and the environment variable that rewrites them
SNAPSHOT_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snapshots')
EMAIL_SNAPSHOT_PATH = os.path.join(SNAPSHOT_DIRECTORY, 'weekly_campaign_brief_vic.email.html')
TEXT_SNAPSHOT_PATH = os.path.join(SNAPSHOT_DIRECTORY, 'weekly_campaign_brief_vic.txt')
UPDATE_SNAPSHOTS_VARIABLE = 'DISPATCH_UPDATE_SNAPSHOTS'

BROWSER_URL = 'https://storage.example.test/sent/r1/slot/browser.html?signature=abc'
CONTACT_EMAIL = 'admin@example.test'

# The em-dash, which must never appear in output
EM_DASH = chr(0x2014)

# Finds the src of every image tag
IMAGE_SOURCE_PATTERN = re.compile(r'<img\b[^>]*\bsrc="([^"]*)"')

# Finds a flexbox or grid display rule, however it is spaced
FLEX_OR_GRID_PATTERN = re.compile(r'display\s*:\s*(flex|grid|inline-flex|inline-grid)', re.IGNORECASE)

# The three charts the brief draws
CHART_CONTENT_IDS = ['statewide_spend-gauge', 'cumulative-biases', 'cumulative-affiliations']

# The browser render embeds PNGs this way
DATA_URI_PREFIX = 'data:image/png;base64,'


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

def render_brief(gold_connection, property_values):
    """Build and render the repository's Weekly Campaign Brief for one set of property values."""
    source = load_template_source(TEMPLATE_DIRECTORY)
    document = record_document(template_id=TEMPLATE_ID, property_values=property_values)
    document['id'] = 'r1'
    record = DispatchRecord.model_validate(document)
    values = source.template.validate_property_values(record.property_values)
    built = build_dispatch(source.template, record, values, gold_connection)
    return render_dispatch(built, source.layout_text, BROWSER_URL, False)


def image_sources(html):
    """The src of every <img> in a render, in order."""
    return IMAGE_SOURCE_PATTERN.findall(html)


def check_snapshot(snapshot_path, actual):
    """Compare text with a stored snapshot, or rewrite the snapshot when asked to."""
    update_requested = os.environ.get(UPDATE_SNAPSHOTS_VARIABLE) == '1'
    if update_requested:
        os.makedirs(SNAPSHOT_DIRECTORY, exist_ok=True)
        with open(snapshot_path, 'w', encoding='utf-8') as snapshot_file:
            snapshot_file.write(actual)
        return

    # A missing snapshot is a failure, so a new one is always written on purpose
    if not os.path.exists(snapshot_path):
        pytest.fail(f'no snapshot at {snapshot_path}; run with {UPDATE_SNAPSHOTS_VARIABLE}=1 to write it')

    with open(snapshot_path, encoding='utf-8') as snapshot_file:
        expected = snapshot_file.read()
    assert actual == expected, f'render differs from {snapshot_path}; refresh with {UPDATE_SNAPSHOTS_VARIABLE}=1'


@pytest.fixture
def victorian(gold_connection):
    """The brief rendered for the VIC state record over the fixtures."""
    return render_brief(gold_connection, {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'state',
        'state': 'VIC',
    })


# ---------------------------------------------------------------- #
# Snapshots
# ---------------------------------------------------------------- #

def test_email_render_matches_snapshot(victorian):
    """The full email HTML for the VIC record matches the stored snapshot."""
    check_snapshot(EMAIL_SNAPSHOT_PATH, victorian.email_html)


def test_plain_text_matches_snapshot(victorian):
    """The plain-text part for the VIC record matches the stored snapshot."""
    check_snapshot(TEXT_SNAPSHOT_PATH, victorian.plain_text)


# ---------------------------------------------------------------- #
# Outlook-safe markup
# ---------------------------------------------------------------- #

def test_no_svg_flexbox_grid_or_em_dash(victorian):
    """Neither render uses SVG, flexbox, grid or an em-dash."""
    for html in (victorian.email_html, victorian.browser_html):
        assert '<svg' not in html.lower()
        assert FLEX_OR_GRID_PATTERN.search(html) is None
        assert EM_DASH not in html
    assert EM_DASH not in victorian.plain_text
    assert EM_DASH not in victorian.subject


def test_mso_conditional_table(victorian):
    """The email wraps its container in the 640px table only Outlook sees."""
    html = victorian.email_html
    assert '<!--[if mso]>' in html
    assert '<table role="presentation" width="640" align="center"' in html
    assert '<![endif]-->' in html


def test_browser_link_line_opens_the_email(victorian):
    """The email opens with the "view in browser" line; the browser copy leaves it out."""
    html = victorian.email_html
    assert 'Not displaying properly?' in html
    assert f'href="{BROWSER_URL}"' in html
    assert html.index('Not displaying properly?') < html.index('Weekly Ad Spend Briefing')
    assert 'Not displaying properly?' not in victorian.browser_html


def test_unsubscribe_contact_footer(victorian):
    """The footer names the contact to email to stop receiving the brief."""
    for html in (victorian.email_html, victorian.browser_html):
        assert 'To stop receiving these emails, contact' in html
        assert f'href="mailto:{CONTACT_EMAIL}"' in html


def test_email_images_use_content_ids(victorian):
    """Every <img> in the email is a cid: reference, one per chart."""
    sources = image_sources(victorian.email_html)
    expected = []
    for content_id in CHART_CONTENT_IDS:
        expected.append(f'cid:{content_id}')
    assert sources == expected


def test_browser_images_are_data_uris(victorian):
    """Every <img> in the browser copy embeds its PNG as a data: URI."""
    sources = image_sources(victorian.browser_html)
    assert len(sources) == len(CHART_CONTENT_IDS)
    for source in sources:
        assert source.startswith(DATA_URI_PREFIX)


# ---------------------------------------------------------------- #
# The layout
# ---------------------------------------------------------------- #

def test_masthead_carries_identity_and_week(victorian):
    """The masthead has the navy rule, the serif title and the week, with no fixed figures."""
    html = victorian.email_html
    assert 'border-bottom: 4px solid #002147' in html
    assert "Georgia, 'Times New Roman', serif" in html
    assert 'Victorian state election' in html
    assert 'Week of 25 September to 1 October 2026' in html
    assert 'Data to 1 October 2026' in html


def test_sections_render_in_template_order(victorian):
    """The four section headings appear in the template's order."""
    html = victorian.email_html
    positions = []
    for heading in ('Statewide spend', 'Cumulative spend', 'Messaging and tone', 'Top 10 seats by spend'):
        positions.append(html.index(heading))
    assert positions == sorted(positions)


def test_fixture_figures_reach_the_brief(victorian):
    """Hand-checked fixture figures appear: the 7-day total, the Liberal card and Kew."""
    html = victorian.email_html
    assert '$4,165' in html
    assert '$2,800' in html
    assert '$2,450' in html
    assert victorian.subject == 'Victorian state election brief, week to 1 October 2026'


def test_layout_holds_no_fixed_figures():
    """The layout file itself carries no dollar amounts or SVG."""
    with open(os.path.join(TEMPLATE_DIRECTORY, 'layout.html.j2'), encoding='utf-8') as layout_file:
        layout_text = layout_file.read()
    assert '$' not in layout_text
    assert '<svg' not in layout_text
    assert FLEX_OR_GRID_PATTERN.search(layout_text) is None


def test_federal_record_renders(gold_connection):
    """A national federal record renders through the same layout."""
    output = render_brief(gold_connection, {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'federal',
    })
    assert 'Federal election' in output.email_html
    assert 'National spend' in output.email_html


# ---------------------------------------------------------------- #
# publish-templates and the local preview
# ---------------------------------------------------------------- #

def test_publish_dry_run_renders_the_brief():
    """The dry run over the repository's templates validates and renders the brief."""
    sources = publish(dry_run=True)
    template_ids = []
    for source in sources:
        template_ids.append(source.template.id)
    assert TEMPLATE_ID in template_ids


def test_render_only_preview_writes_both_copies(tmp_path):
    """The local render writes the email, the browser copy, the charts and the text, with no cloud access."""
    out_directory = tmp_path / 'out'
    exit_code = main([
        '--render-only',
        '--record-file', EXAMPLE_RECORD_PATH,
        '--data-dir', FIXTURE_GOLD_DIRECTORY,
        '--lookups-dir', FIXTURE_LOOKUPS_DIRECTORY,
        '--out', str(out_directory),
    ])
    assert exit_code == 0

    # Every expected file is there
    written = sorted(os.listdir(out_directory))
    expected = ['browser.html', 'email.html', 'email.txt', 'message.eml']
    for content_id in CHART_CONTENT_IDS:
        expected.append(f'{content_id}.png')
    assert written == sorted(expected)

    # The email's browser link points at the local browser copy
    email_html = (out_directory / 'email.html').read_text(encoding='utf-8')
    assert 'href="browser.html"' in email_html
    browser_html = (out_directory / 'browser.html').read_text(encoding='utf-8')
    assert DATA_URI_PREFIX in browser_html
    plain_text = (out_directory / 'email.txt').read_text(encoding='utf-8')
    assert 'Figures reflect the 7-day window 25 September to 1 October 2026.' in plain_text


def test_render_only_needs_record_file_and_data():
    """--render-only without its inputs is a usage error."""
    with pytest.raises(SystemExit):
        main(['--render-only'])
