"""
Fetch a template's layout and render it with Jinja2.

A layout (`templates/<id>/layout.html.j2`) extends the shared skeleton
(`email_skeleton.html.j2`) and includes each section's partial. The Jinja2
environment finds templates in three places, in this order:

  1. The layout itself, registered under the name `layout.html.j2`.
  2. The section partials, each in the directory of its section module
     (normally `dispatch/sections/`, which ships in the image).
  3. The skeleton in `dispatch/render/`.

The same layout renders twice: once for the email (images by `cid:`) and once
for the browser copy (images embedded as base64).
"""

import base64
import os
from dataclasses import dataclass, field

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined

from dispatch import formatting
from dispatch.config import DISPATCH_BUCKET, PROJECT_ID


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The name the layout is registered under in the environment
LAYOUT_NAME = 'layout.html.j2'

# Where the partials and the skeleton live inside the package
PACKAGE_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS_DIRECTORY = os.path.join(PACKAGE_DIRECTORY, 'sections')
RENDER_DIRECTORY = os.path.join(PACKAGE_DIRECTORY, 'render')

# The two ways images are referenced
EMAIL_MODE = 'email'
BROWSER_MODE = 'browser'

# Formatting helpers available to every template as filters
TEMPLATE_FILTERS = {
    'money': formatting.format_money,
    'money_short': formatting.format_money_short,
    'percent': formatting.format_percent,
    'long_date': formatting.format_long_date,
    'day_month': formatting.format_day_month,
    'short_date': formatting.format_short_date,
}


# ---------------------------------------------------------------- #
# Layout stores
# ---------------------------------------------------------------- #

class LayoutStore:
    """Reads a template's layout text from wherever layouts are kept."""

    def read_layout(self, layout_path):
        """Return the layout's text for a path such as `templates/<id>/layout.html.j2`."""
        raise NotImplementedError


class LocalLayoutStore(LayoutStore):
    """Reads layouts from the repository on disk."""

    def __init__(self, root_directory):
        """Remember the directory layout paths are relative to."""
        self.root_directory = root_directory

    def read_layout(self, layout_path):
        """Read the layout file from under the root directory."""
        full_path = os.path.join(self.root_directory, layout_path)
        with open(full_path, encoding='utf-8') as layout_file:
            return layout_file.read()


class GcsLayoutStore(LayoutStore):
    """Reads layouts from the Dispatch bucket, where publish-templates puts them."""

    def __init__(self, storage_client=None, bucket_name=DISPATCH_BUCKET):
        """Remember the bucket and the storage client to use."""
        self.storage_client = storage_client
        self.bucket_name = bucket_name

    def client(self):
        """The storage client, created on first use."""
        if self.storage_client is None:
            from google.cloud import storage
            self.storage_client = storage.Client(project=PROJECT_ID)
        return self.storage_client

    def read_layout(self, layout_path):
        """Download the layout object's text."""
        bucket = self.client().bucket(self.bucket_name)
        blob = bucket.blob(layout_path)
        return blob.download_as_text(encoding='utf-8')


# ---------------------------------------------------------------- #
# What a template sees
# ---------------------------------------------------------------- #

@dataclass
class RenderedImage:
    """An image as a template uses it: its src, display size and alt text."""
    src: str
    width: int
    height: int
    alt: str
    content_id: str


@dataclass
class RenderedSection:
    """A built section as a template sees it, as `section` inside its partial."""
    id: str
    type: str
    partial: str
    variables: dict
    images: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def image_source(image, content_id, mode):
    """The `src` for one image: a `cid:` reference in email, a base64 data URI in the browser."""
    if mode == EMAIL_MODE:
        return f'cid:{content_id}'
    encoded = base64.b64encode(image.png).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def rendered_sections(built_sections, mode):
    """Turn built sections into what the templates see, with image sources for one mode."""
    sections = []
    for built in built_sections:
        # Each image is reached by its name, as in section.images.gauge.src
        images = {}
        for image in built.result.images:
            content_id = image.content_id(built.config.id)
            images[image.name] = RenderedImage(
                src=image_source(image, content_id, mode),
                width=image.display_width,
                height=image.display_height,
                alt=image.alt,
                content_id=content_id,
            )

        sections.append(RenderedSection(
            id=built.config.id,
            type=built.config.type,
            partial=built.module.PARTIAL,
            variables=built.result.variables,
            images=images,
            notes=built.result.notes,
        ))
    return sections


# ---------------------------------------------------------------- #
# The environment
# ---------------------------------------------------------------- #

def partial_directories_for(built_sections):
    """The directories holding the partials of the sections built, each section's module directory."""
    directories = []
    for built in built_sections:
        module_directory = os.path.dirname(os.path.abspath(built.module.__file__))
        if module_directory in directories:
            continue
        directories.append(module_directory)
    return directories


def build_environment(layout_text, partial_directories=()):
    """A Jinja2 environment holding the layout, the section partials and the skeleton."""
    # Partials are searched for beside their section modules, then in the package's sections folder
    search_directories = list(partial_directories)
    if SECTIONS_DIRECTORY not in search_directories:
        search_directories.append(SECTIONS_DIRECTORY)

    loader = ChoiceLoader([
        DictLoader({LAYOUT_NAME: layout_text}),
        FileSystemLoader(search_directories),
        FileSystemLoader(RENDER_DIRECTORY),
    ])

    # Escape everything; a missing variable is an error, not an empty string
    environment = Environment(
        loader=loader,
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )

    for filter_name, filter_function in TEMPLATE_FILTERS.items():
        environment.filters[filter_name] = filter_function
    return environment


def render_layout(layout_text, dispatch_variables, sections, partial_directories=()):
    """Render the layout with the dispatch-wide variables and the sections."""
    environment = build_environment(layout_text, partial_directories)
    layout = environment.get_template(LAYOUT_NAME)
    return layout.render(dispatch=dispatch_variables, sections=sections)
