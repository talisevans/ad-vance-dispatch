"""
The publish-templates command: validate the repository's templates and publish
them for the job and the MCP tools to read.

    python -m dispatch.publish_templates [--template <id>] [--dry-run]

  1. Load every `templates/*/template.json` and validate it, including each
     section's params against its type's own model.
  2. Render each template against the test fixtures, to catch layout and
     partial errors before 9am Monday.
  3. Upload `layout.html.j2` to `gs://advance_dispatch/templates/<id>/`.
  4. Upsert `dispatch_templates/<id>` in Firestore.
  5. Write `dispatch_catalogue/template_schema` and
     `dispatch_catalogue/section_types`.

`--dry-run` does steps 1 and 2 only.
"""

import argparse
import datetime
import json
import os
import sys
from dataclasses import dataclass

from dispatch.build import build_dispatch, render_dispatch
from dispatch.config import (
    CATALOGUE_SECTION_TYPES_DOCUMENT,
    CATALOGUE_TEMPLATE_SCHEMA_DOCUMENT,
    TEMPLATES_PREFIX,
)
from dispatch.data.gold import LocalGoldSource, open_gold_from
from dispatch.filters.registry import catalogue_entries
from dispatch.models.record import DispatchRecord
from dispatch.models.template import PROPERTY_TYPES, SUBJECT_PLACEHOLDERS, SUPPORTED_SCHEMA_VERSIONS, Template
from dispatch.sections.registry import SECTION_TYPES


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The repository root, two levels above this package
REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Where templates and the fixtures live in the repository
TEMPLATES_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'templates')
FIXTURE_GOLD_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'tests', 'fixtures', 'gold')
FIXTURE_LOOKUPS_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'tests', 'fixtures', 'lookups')

# Each template's files
TEMPLATE_FILE_NAME = 'template.json'
LAYOUT_FILE_NAME = 'layout.html.j2'

# The data range a fixture render uses: the fixtures run from August to early October 2026
FIXTURE_START_DATE = '2026-08-01'
FIXTURE_END_DATE = '2026-11-28'

# Sample values for the other property types in a fixture render
SAMPLE_STRING = 'Sample'
SAMPLE_NUMBER = 1
SAMPLE_AFFILIATIONS = ['aff_labor']

# The link a fixture render quotes in place of a signed one
FIXTURE_BROWSER_URL = 'https://storage.example.test/browser.html'

# What each subject placeholder holds, for the catalogue
SUBJECT_PLACEHOLDER_DESCRIPTIONS = {
    'jurisdiction_label': 'The record\'s jurisdiction, e.g. "Victorian state" or "Federal".',
    'as_of_long': 'The as_of date in full, e.g. "1 October 2026".',
    'window_start_long': 'The first day of the 7-day window in full.',
    'template_name': 'The template\'s name.',
    'record_name': 'The Dispatch Record\'s name.',
}

# The authoring rules shipped to the dispatch_template_guide MCP tool (plan section 9.2)
AUTHORING_RULES = [
    'Reuse an existing section type when its params can express the need. Add params before adding a type.',
    'Never put jurisdiction or state in a template\'s filters; they come from the record.',
    'Use ids, never display names, in filters and cards.',
    'Themes overlap; never sum them.',
    'Respect the as_of window; never use the run date for data.',
    'Charts must be PNG; everything else must be table markup.',
]

# Notes that annotate the example template in the catalogue
EXAMPLE_NOTES = [
    'globals.exclude.classification drops government advertising from every section.',
    'Each section names a reusable type; params are validated against that type\'s own model.',
    'top_seats narrows further with its own include; a section can only narrow the globals.',
    'Messaging cards list affiliation ids, never names.',
]


@dataclass
class TemplateSource:
    """One template from the repository: the parsed model, its directory and its layout text."""
    template: Template
    directory: str
    layout_text: str
    raw: dict


def log(message):
    """Write one line to the command's output."""
    print(f'[publish-templates] {message}', flush=True)


# ---------------------------------------------------------------- #
# Step 1: load and validate
# ---------------------------------------------------------------- #

def template_directories(templates_directory, only_template_id=None):
    """Every template directory under the templates folder, or just the one asked for."""
    if not os.path.isdir(templates_directory):
        return []

    directories = []
    for name in sorted(os.listdir(templates_directory)):
        directory = os.path.join(templates_directory, name)
        has_template_file = os.path.isfile(os.path.join(directory, TEMPLATE_FILE_NAME))
        if not has_template_file:
            continue
        if only_template_id is not None and name != only_template_id:
            continue
        directories.append(directory)
    return directories


def load_template_source(directory):
    """Read and validate one template directory's template.json and layout."""
    template_path = os.path.join(directory, TEMPLATE_FILE_NAME)
    with open(template_path, encoding='utf-8') as template_file:
        raw = json.load(template_file)
    template = Template.model_validate(raw)

    # The folder name, the id and the layout path must all agree
    folder_name = os.path.basename(directory)
    if template.id != folder_name:
        raise ValueError(f'{template_path}: id "{template.id}" does not match its folder "{folder_name}"')
    expected_layout_path = f'{TEMPLATES_PREFIX}{template.id}/{LAYOUT_FILE_NAME}'
    if template.layout_path != expected_layout_path:
        raise ValueError(f'{template_path}: layout_path must be "{expected_layout_path}"')

    layout_path = os.path.join(directory, LAYOUT_FILE_NAME)
    with open(layout_path, encoding='utf-8') as layout_file:
        layout_text = layout_file.read()

    return TemplateSource(template=template, directory=directory, layout_text=layout_text, raw=raw)


def load_template_sources(templates_directory, only_template_id=None):
    """Load and validate every template, failing on the first that is invalid."""
    sources = []
    for directory in template_directories(templates_directory, only_template_id):
        source = load_template_source(directory)
        log(f'validated {source.template.id}')
        sources.append(source)
    return sources


# ---------------------------------------------------------------- #
# Step 2: render against the fixtures
# ---------------------------------------------------------------- #

def sample_value(definition, key_values):
    """A sample value for one property, for a fixture render."""
    if definition.key in key_values:
        return key_values[definition.key]
    if definition.type == 'date':
        if definition.key == 'start_date':
            return FIXTURE_START_DATE
        return FIXTURE_END_DATE
    if definition.type == 'enum':
        return definition.options[0]
    if definition.type == 'string':
        return SAMPLE_STRING
    if definition.type == 'number':
        return SAMPLE_NUMBER
    return list(SAMPLE_AFFILIATIONS)


def sample_property_values(template, chosen_values):
    """A full set of property values, with some chosen and the rest sampled."""
    values = {}

    # Fill properties in order, so required_when sees the values chosen before it
    for definition in template.required_properties:
        candidate = dict(values)
        candidate.update(chosen_values)
        if not definition.is_required(candidate):
            continue
        values[definition.key] = sample_value(definition, chosen_values)
    return values


def sample_property_sets(template):
    """One sample set with first options, plus one per required_when condition so every branch renders."""
    sets = [sample_property_values(template, {})]

    for definition in template.required_properties:
        if not definition.required_when:
            continue
        sample = sample_property_values(template, dict(definition.required_when))
        if sample not in sets:
            sets.append(sample)
    return sets


def fixture_record(template, property_values):
    """A record that exists only for a fixture render."""
    return DispatchRecord(
        id='fixture',
        name=f'{template.name} (fixture render)',
        template_id=template.id,
        template_schema_version=template.schema_version,
        property_values=property_values,
        recipients=['fixture@example.test'],
        contact_email='contact@example.test',
        cron='0 9 * * 1',
        timezone='Australia/Melbourne',
        start_delivery=FIXTURE_START_DATE,
        end_delivery=FIXTURE_END_DATE,
        status='active',
    )


def render_against_fixtures(source, gold_directory=FIXTURE_GOLD_DIRECTORY,
                            lookups_directory=FIXTURE_LOOKUPS_DIRECTORY):
    """Build and render a template against the fixtures for every sample property set."""
    renders = []
    gold_source = LocalGoldSource(gold_directory, lookups_directory)

    for property_values in sample_property_sets(source.template):
        cleaned = source.template.validate_property_values(property_values)
        record = fixture_record(source.template, cleaned)

        connection = open_gold_from(gold_source)
        try:
            built = build_dispatch(source.template, record, cleaned, connection)
        finally:
            connection.close()

        rendered = render_dispatch(built, source.layout_text, FIXTURE_BROWSER_URL, False)
        log(f'rendered {source.template.id} with {cleaned}')
        renders.append(rendered)
    return renders


# ---------------------------------------------------------------- #
# Steps 3 and 4: upload and upsert
# ---------------------------------------------------------------- #

def publish_template(source, bucket, store, published_at):
    """Upload the layout and write the template document."""
    bucket.upload(source.template.layout_path, source.layout_text, 'text/plain; charset=utf-8')

    document = source.template.model_dump(mode='json')
    document['published_at'] = published_at
    store.upsert_template(source.template.id, document)
    log(f'published {source.template.id}')


# ---------------------------------------------------------------- #
# Step 5: the catalogue
# ---------------------------------------------------------------- #

def template_schema_document(sources, generated_at):
    """The catalogue document describing how to write a template."""
    placeholders = []
    for name in SUBJECT_PLACEHOLDERS:
        placeholders.append({'name': name, 'description': SUBJECT_PLACEHOLDER_DESCRIPTIONS[name]})

    # The first template in the repository serves as the annotated example
    example = None
    if sources:
        example = sources[0].raw

    return {
        'generated_at': generated_at,
        'supported_schema_versions': sorted(SUPPORTED_SCHEMA_VERSIONS),
        'template_json_schema': json.dumps(Template.model_json_schema()),
        'filter_registry': catalogue_entries(),
        'property_types': list(PROPERTY_TYPES),
        'subject_placeholders': placeholders,
        'authoring_rules': list(AUTHORING_RULES),
        'example_template': example,
        'example_notes': list(EXAMPLE_NOTES),
    }


def section_uses(sources, type_name):
    """Every template section that uses a section type, with that instance's config."""
    uses = []
    for source in sources:
        for section in source.template.sections:
            if section.type != type_name:
                continue
            uses.append({
                'template_id': source.template.id,
                'section_id': section.id,
                'params': section.params,
                'include': section.include,
                'exclude': section.exclude,
            })
    return uses


def section_types_document(sources, generated_at):
    """The catalogue document describing every registered section type."""
    types = []
    for type_name in sorted(SECTION_TYPES):
        section_module = SECTION_TYPES[type_name]
        params_schema = section_module.Params.model_json_schema()
        types.append({
            'type': type_name,
            'description': section_module.DESCRIPTION,
            'renders': section_module.RENDERS,
            'partial': section_module.PARTIAL,
            'params_json_schema': json.dumps(params_schema),
            'used_by': section_uses(sources, type_name),
        })
    return {'generated_at': generated_at, 'section_types': types}


def write_catalogue(sources, store, generated_at):
    """Write both catalogue documents."""
    store.write_catalogue(CATALOGUE_TEMPLATE_SCHEMA_DOCUMENT, template_schema_document(sources, generated_at))
    store.write_catalogue(CATALOGUE_SECTION_TYPES_DOCUMENT, section_types_document(sources, generated_at))
    log('wrote the catalogue')


# ---------------------------------------------------------------- #
# The command
# ---------------------------------------------------------------- #

def publish(only_template_id=None, dry_run=False, bucket=None, store=None,
            templates_directory=TEMPLATES_DIRECTORY):
    """Run the five steps, or the first two on a dry run. Returns the template sources handled."""
    sources = load_template_sources(templates_directory, only_template_id)
    if not sources:
        log('no templates found')

    # Step 2 for every template before anything is published
    for source in sources:
        render_against_fixtures(source)

    if dry_run:
        log('dry run: nothing published')
        return sources

    # Steps 3 and 4 for each template
    published_at = datetime.datetime.now(datetime.timezone.utc)
    for source in sources:
        publish_template(source, bucket, store, published_at)

    # The catalogue always describes every template in the repository, even on a single publish
    all_sources = sources
    if only_template_id is not None:
        all_sources = load_template_sources(templates_directory)
    write_catalogue(all_sources, store, published_at)
    return sources


def parse_arguments(arguments):
    """Read the command line."""
    parser = argparse.ArgumentParser(description='Validate and publish Dispatch templates.')
    parser.add_argument('--template', default=None, help='Publish only this template id.')
    parser.add_argument('--dry-run', action='store_true', help='Validate and render only.')
    return parser.parse_args(arguments)


def main(arguments=None):
    """Run publish-templates and return the exit code."""
    options = parse_arguments(arguments)

    bucket = None
    store = None
    if not options.dry_run:
        from dispatch.delivery.archive import GcsArchiveStore
        from dispatch.store.firestore import FirestoreDispatchStore
        bucket = GcsArchiveStore()
        store = FirestoreDispatchStore()

    publish(options.template, options.dry_run, bucket, store)
    return 0


if __name__ == '__main__':
    sys.exit(main())
