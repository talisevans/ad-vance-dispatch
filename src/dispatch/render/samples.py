"""
Render samples of sections and whole emails for people and the MCP tools to look at.

A sample is rendered with the same partials, layout and Jinja2 environment as a
real Dispatch, over the made-up test data, with two differences:

  1. CSS stays in a <style> block instead of being inlined, so the HTML is short
     enough to read.
  2. Each chart image is swapped for a box describing the chart, because an
     embedded PNG is large and a reader cannot see inside it.

Every sample carries a notice that its figures are made up.
"""

from lxml import html as lxml_html

from dispatch.build import dispatch_variables, make_subject
from dispatch.render.layout import (
    BROWSER_MODE,
    LAYOUT_NAME,
    build_environment,
    partial_directories_for,
    rendered_sections,
)


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The notice at the top of every sample, and in the catalogue beside it
SAMPLE_NOTICE = (
    'Sample rendered from made-up test data. '
    'None of these figures are real and they must never be quoted as AdVance data.'
)

# The template a sample sits in, from dispatch/render/
SAMPLE_FRAME_NAME = 'sample_frame.html.j2'

# The class and style the chart description box takes, so it reads the same in any sample
SAMPLE_CHART_CLASS = 'sample-chart'
SAMPLE_CHART_STYLE = (
    'padding: 24px 16px; border: 1px dashed #9ca3af; background-color: #f9fafb; '
    'font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 18px; '
    'color: #4b5563; text-align: center;'
)

# The style of the visible made-up data notice
SAMPLE_NOTICE_STYLE = (
    'padding: 10px 24px; background-color: #fff8e6; font-family: Arial, Helvetica, sans-serif; '
    'font-size: 12px; line-height: 18px; color: #4a3d05; text-align: center;'
)


# ---------------------------------------------------------------- #
# Chart descriptions
# ---------------------------------------------------------------- #

def chart_description(image_element):
    """The text that stands in for one chart: its display size and its alt text."""
    width = image_element.get('width', '?')
    height = image_element.get('height', '?')
    alt = image_element.get('alt', '')
    return f'[Chart, {width}x{height}px: {alt}]'


def describe_charts(document):
    """Replace every <img> in a parsed sample with a box describing the chart."""
    # Collect the images first, so replacing them does not disturb the walk
    image_elements = list(document.iter('img'))

    # Swap each image for a description box, keeping its place in the layout
    for image_element in image_elements:
        box = lxml_html.Element('div')
        box.set('class', SAMPLE_CHART_CLASS)
        box.set('style', SAMPLE_CHART_STYLE)
        box.text = chart_description(image_element)
        box.tail = image_element.tail
        parent = image_element.getparent()
        parent.replace(image_element, box)


# ---------------------------------------------------------------- #
# The made-up data notice
# ---------------------------------------------------------------- #

def add_notice(document):
    """Put the made-up data notice at the top of the body, as a comment and as a visible line."""
    body = document.body

    # A visible line, so anyone opening the sample sees it first
    banner = lxml_html.Element('div')
    banner.set('style', SAMPLE_NOTICE_STYLE)
    banner.text = SAMPLE_NOTICE
    body.insert(0, banner)

    # A comment, so anything reading the source sees it too
    comment = lxml_html.HtmlComment(f' {SAMPLE_NOTICE} ')
    body.insert(0, comment)


def finish_sample(html_text):
    """Describe the charts in rendered HTML, add the notice, and return the finished sample."""
    document = lxml_html.document_fromstring(html_text)
    describe_charts(document)
    add_notice(document)
    return lxml_html.tostring(document, encoding='unicode', doctype='<!DOCTYPE html>')


# ---------------------------------------------------------------- #
# Rendering
# ---------------------------------------------------------------- #

def sample_variables(title):
    """The variables the sample frame reads as `sample`."""
    return {'title': title}


def render_section_sample(built_section):
    """Render one built section on its own, in the sample frame, with its charts described."""
    sections = rendered_sections([built_section], BROWSER_MODE)
    partial_directories = partial_directories_for([built_section])

    # The sample frame needs no layout, so the layout slot is left empty
    environment = build_environment('', partial_directories)
    frame = environment.get_template(SAMPLE_FRAME_NAME)
    title = f'Sample: {built_section.config.type} section'
    html_text = frame.render(sample=sample_variables(title), sections=sections)
    return finish_sample(html_text)


def render_email_sample(built, layout_text):
    """Render a whole email in its layout, CSS not inlined, with its charts described."""
    subject = make_subject(built, False)
    variables = dispatch_variables(built, BROWSER_MODE, subject, '', False)
    sections = rendered_sections(built.sections, BROWSER_MODE)
    partial_directories = partial_directories_for(built.sections)

    # Render the layout exactly as a real Dispatch does, but leave the CSS in its <style> block
    environment = build_environment(layout_text, partial_directories)
    layout = environment.get_template(LAYOUT_NAME)
    html_text = layout.render(dispatch=variables, sections=sections)
    return finish_sample(html_text)
