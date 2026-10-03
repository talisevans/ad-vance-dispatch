"""
Render and message tests: the Outlook-safe skeleton, the two render modes,
CSS inlining, the MIME structure, and the chart style's PNG output.
"""

import io
import struct

import pytest

from dispatch.build import build_dispatch, render_dispatch
from dispatch.charts.style import DENSITY, HALF_CHART_WIDTH, chart_image, new_figure, style_axes
from dispatch.delivery.message import build_message
from dispatch.models.record import DispatchRecord
from dispatch.models.template import Template
from tests.conftest import PROBE_LAYOUT_PATH, probe_template_document, record_document


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

BROWSER_URL = 'https://storage.example.test/sent/r1/slot/browser.html?signature=abc'

# The em-dash, which must never appear in output
EM_DASH = chr(0x2014)


@pytest.fixture
def rendered(registered_probe, gold_connection):
    """The probe template built and rendered against the fixtures for a VIC record."""
    template = Template.model_validate(probe_template_document())
    document = record_document()
    document['id'] = 'r1'
    record = DispatchRecord.model_validate(document)
    values = template.validate_property_values(record.property_values)
    built = build_dispatch(template, record, values, gold_connection)

    with open(PROBE_LAYOUT_PATH, encoding='utf-8') as layout_file:
        layout_text = layout_file.read()
    return built, render_dispatch(built, layout_text, BROWSER_URL, False)


def png_size(png):
    """The pixel width and height recorded in a PNG's header."""
    width, height = struct.unpack('>II', png[16:24])
    return width, height


# ---------------------------------------------------------------- #
# The skeleton
# ---------------------------------------------------------------- #

def test_email_render_is_outlook_safe(rendered):
    """The email keeps its doctype, the MSO conditional table and presentation tables."""
    _built, output = rendered
    html = output.email_html
    assert html.startswith('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"')
    assert '<!--[if mso]>' in html
    assert '<table role="presentation" width="640"' in html
    assert 'xmlns:o="urn:schemas-microsoft-com:office:office"' in html
    assert '<svg' not in html
    assert 'display: flex' not in html
    assert 'display:flex' not in html


def test_email_opens_with_the_browser_link(rendered):
    """The first line inside the frame links to the signed browser copy."""
    _built, output = rendered
    html = output.email_html
    assert 'Not displaying properly?' in html
    assert 'href="https://storage.example.test/sent/r1/slot/browser.html?signature=abc"' in html
    link_position = html.index('Not displaying properly?')
    title_position = html.index('Probe Brief</p>')
    assert link_position < title_position


def test_browser_copy_has_no_browser_link_and_embeds_images(rendered):
    """The browser copy drops the link and carries its charts as base64."""
    _built, output = rendered
    assert 'Not displaying properly?' not in output.browser_html
    assert 'src="data:image/png;base64,' in output.browser_html
    assert 'cid:' not in output.browser_html


def test_email_references_images_by_content_id(rendered):
    """Each chart is referenced by its section-scoped Content-ID."""
    _built, output = rendered
    assert 'src="cid:statewide-bar"' in output.email_html
    assert 'src="cid:participants-bar"' in output.email_html


def test_footer_carries_source_window_and_contact(rendered):
    """The footer has the data source, the window sentence and the unsubscribe contact."""
    _built, output = rendered
    html = output.email_html
    assert 'Source: Meta Ad Library and Google Ads Transparency Center' in html
    assert 'Figures reflect the 7-day window 25 September to 1 October 2026.' in html
    assert 'To stop receiving these emails, contact' in html
    assert 'mailto:admin@example.test' in html


def test_css_is_inlined(rendered):
    """Class rules land on the elements; only media queries stay in a style block."""
    _built, output = rendered
    html = output.email_html
    assert 'class="note-text" style="font-family:Arial' in html
    assert '.body-text {' not in html
    assert '@media screen and (max-width: 640px)' in html


def test_subject_and_plain_text(rendered):
    """The subject fills its placeholders; the plain text has figures, window and link."""
    _built, output = rendered
    assert output.subject == 'Victorian state probe brief, week to 1 October 2026'
    assert 'Probe total: $4,165' in output.plain_text
    assert 'Probe total: $3,640' in output.plain_text
    assert 'Figures reflect the 7-day window 25 September to 1 October 2026.' in output.plain_text
    assert BROWSER_URL in output.plain_text


def test_no_em_dash_in_output(rendered):
    """No em-dash appears in any part of the email."""
    _built, output = rendered
    assert EM_DASH not in output.email_html
    assert EM_DASH not in output.browser_html
    assert EM_DASH not in output.plain_text


# ---------------------------------------------------------------- #
# The MIME message
# ---------------------------------------------------------------- #

def test_mime_structure_and_headers(rendered):
    """related holds alternative (plain then HTML) and one PNG per chart with its Content-ID."""
    built, output = rendered
    message, message_id = build_message(output, built.images, 'alice@example.test', 'contact@example.test')

    assert message.get_content_type() == 'multipart/related'
    assert message['From'] == 'AdVance Dispatch <no-reply@talisevans.dev>'
    assert message['To'] == 'alice@example.test'
    assert message['Reply-To'] == 'contact@example.test'
    assert message['Message-ID'] == message_id

    parts = message.get_payload()
    assert parts[0].get_content_type() == 'multipart/alternative'
    alternative_types = []
    for part in parts[0].get_payload():
        alternative_types.append(part.get_content_type())
    assert alternative_types == ['text/plain', 'text/html']

    content_ids = []
    for part in parts[1:]:
        assert part.get_content_type() == 'image/png'
        content_ids.append(part['Content-ID'])
    assert content_ids == ['<statewide-bar>', '<participants-bar>']


# ---------------------------------------------------------------- #
# Chart style
# ---------------------------------------------------------------- #

def test_chart_png_is_twice_display_size_on_white():
    """A 290 by 120 chart saves as a 580 by 240 PNG with no transparency."""
    figure, axes = new_figure(HALF_CHART_WIDTH, 120)
    style_axes(axes)
    axes.plot([0, 1], [0, 1])
    image = chart_image('test', figure, HALF_CHART_WIDTH, 120, 'A test line')

    assert png_size(image.png) == (HALF_CHART_WIDTH * DENSITY, 120 * DENSITY)
    assert image.display_width == HALF_CHART_WIDTH
    assert image.alt == 'A test line'

    # Colour type 2 is RGB with no alpha channel
    colour_type = image.png[25]
    assert colour_type == 2 or _corner_is_opaque_white(image.png)


def _corner_is_opaque_white(png):
    """Whether the PNG's top-left pixel is fully opaque white."""
    from matplotlib import image as matplotlib_image

    pixels = matplotlib_image.imread(io.BytesIO(png), format='png')
    corner = pixels[0][0]
    is_white = corner[0] == 1.0 and corner[1] == 1.0 and corner[2] == 1.0
    is_opaque = len(corner) == 3 or corner[3] == 1.0
    return is_white and is_opaque
