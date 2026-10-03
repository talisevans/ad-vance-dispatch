"""
The publish-templates command: validate the templates, render samples, and
publish everything the job, the API and the MCP tools read.

    python -m dispatch.publish_templates --dry-run
    python -m dispatch.main publish-templates --build-tag <tag>   (inside the image only)

  1. Load every `templates/emails/*/template.json` and validate it, including
     each section's params against its type's own model.
  2. Render each template against the made-up test data, to catch layout and
     partial errors before 9am Monday.
  3. Render samples: one per email template and one per section type.
  4. Upload to `gs://advance_dispatch/templates/`:
       emails/<id>/layout.html.j2       the layout the job reads at send time
       emails/<id>/sample.html          the whole email, made-up figures
       sections/<type>/<type>.html.j2   a read-only copy of the partial
       sections/<type>/sample.html      the section alone, made-up figures
  5. Upsert `dispatch_templates/<id>` in Firestore.
  6. Write `dispatch_catalogue/template_schema` and
     `dispatch_catalogue/section_types`. They name each sample and partial by
     its bucket path; the bucket holds the one copy of every file.

`--dry-run` does steps 1 to 3 and publishes nothing. A real publish runs only
inside a Cloud Run execution of the deployed image, so everything it writes
comes from the code the job is running. `deploy/deploy.sh deploy` starts that
execution and passes the image's build tag, which is stamped on every document.
"""

import argparse
import datetime
import json
import os
import sys
from dataclasses import dataclass, field

from dispatch.build import build_dispatch, render_dispatch
from dispatch.config import (
    CATALOGUE_SECTION_TYPES_DOCUMENT,
    CATALOGUE_TEMPLATE_SCHEMA_DOCUMENT,
    EMAIL_TEMPLATES_PREFIX,
    LAYOUT_FILE_NAME,
    SAMPLE_FILE_NAME,
    SECTION_TEMPLATES_PREFIX,
    home_directory,
    running_in_cloud_run,
)
from dispatch.data.gold import LocalGoldSource, open_gold_from
from dispatch.filters.registry import catalogue_entries
from dispatch.models.record import DispatchRecord
from dispatch.models.template import PROPERTY_TYPES, SUBJECT_PLACEHOLDERS, SUPPORTED_SCHEMA_VERSIONS, Template
from dispatch.render.samples import SAMPLE_NOTICE, render_email_sample, render_section_sample
from dispatch.sections.registry import SECTION_TYPES


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# Where the email templates and the made-up test data live, under the home directory
TEMPLATES_DIRECTORY = os.path.join(home_directory(), 'templates', 'emails')
FIXTURE_GOLD_DIRECTORY = os.path.join(home_directory(), 'tests', 'fixtures', 'gold')
FIXTURE_LOOKUPS_DIRECTORY = os.path.join(home_directory(), 'tests', 'fixtures', 'lookups')

# Each template's definition file
TEMPLATE_FILE_NAME = 'template.json'

# The content types the uploads carry
JINJA_CONTENT_TYPE = 'text/plain; charset=utf-8'
HTML_CONTENT_TYPE = 'text/html; charset=utf-8'

# The data range a fixture render uses: the fixtures run from August to early October 2026
FIXTURE_START_DATE = '2026-08-01'
FIXTURE_END_DATE = '2026-11-28'

# Sample values for the other property types in a fixture render
SAMPLE_STRING = 'Sample'
SAMPLE_NUMBER = 1
SAMPLE_AFFILIATIONS = ['aff_labor']

# The scope section samples are rendered for: one state's state seats
SECTION_SAMPLE_JURISDICTION = 'state'
SECTION_SAMPLE_STATE = 'VIC'

# The link a fixture render quotes in place of a signed one
FIXTURE_BROWSER_URL = 'https://storage.example.test/browser.html'

# The build tag a dry run reports, since it publishes nothing
DRY_RUN_BUILD_TAG = 'dry-run'

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
    """One email template from the repository: the parsed model, its folder, its layout and its sample."""
    template: Template
    directory: str
    layout_text: str
    raw: dict
    sample_html: str = ''


@dataclass
class SectionSample:
    """One section type's published files: its partial's source and its rendered sample."""
    type_name: str
    partial_source: str
    sample_html: str


@dataclass
class PublishPlan:
    """Everything a publish writes, rendered before anything is written."""
    sources: list
    all_sources: list
    section_samples: dict = field(default_factory=dict)


def log(message):
    """Write one line to the command's output."""
    print(f'[publish-templates] {message}', flush=True)


# ---------------------------------------------------------------- #
# Bucket paths
# ---------------------------------------------------------------- #

def email_layout_path(template_id):
    """Where an email template's layout lives in the bucket."""
    return f'{EMAIL_TEMPLATES_PREFIX}{template_id}/{LAYOUT_FILE_NAME}'


def email_sample_path(template_id):
    """Where an email template's sample lives in the bucket."""
    return f'{EMAIL_TEMPLATES_PREFIX}{template_id}/{SAMPLE_FILE_NAME}'


def section_partial_path(type_name, partial_file_name):
    """Where the read-only copy of a section's partial lives in the bucket."""
    return f'{SECTION_TEMPLATES_PREFIX}{type_name}/{partial_file_name}'


def section_sample_path(type_name):
    """Where a section type's sample lives in the bucket."""
    return f'{SECTION_TEMPLATES_PREFIX}{type_name}/{SAMPLE_FILE_NAME}'


# ---------------------------------------------------------------- #
# Step 1: load and validate
# ---------------------------------------------------------------- #

def template_directories(templates_directory, only_template_id=None):
    """Every template directory under the email templates folder, or just the one asked for."""
    if not os.path.isdir(templates_directory):
        return []

    directories = []
    for name in sorted(os.listdir(templates_directory)):
        directory = os.path.join(templates_directory, name)

        # Skip anything that is not a template folder
        has_template_file = os.path.isfile(os.path.join(directory, TEMPLATE_FILE_NAME))
        if not has_template_file:
            continue

        # Skip the others when only one was asked for
        is_other_template = only_template_id is not None and name != only_template_id
        if is_other_template:
            continue
        directories.append(directory)
    return directories


def load_template_source(directory):
    """Read and validate one template directory's template.json and layout."""
    template_path = os.path.join(directory, TEMPLATE_FILE_NAME)
    with open(template_path, encoding='utf-8') as template_file:
        raw = json.load(template_file)
    template = Template.model_validate(raw)

    # The folder name and the id must agree
    folder_name = os.path.basename(directory)
    if template.id != folder_name:
        raise ValueError(f'{template_path}: id "{template.id}" does not match its folder "{folder_name}"')

    # The layout path must be the one the bucket uses for this template
    expected_layout_path = email_layout_path(template.id)
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

    # Dates span the fixtures; other types take a fixed sample
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


def build_against_fixtures(template, property_values, gold_directory, lookups_directory):
    """Build one Dispatch of a template over the fixtures, for one set of property values."""
    cleaned = template.validate_property_values(property_values)
    record = fixture_record(template, cleaned)
    gold_source = LocalGoldSource(gold_directory, lookups_directory)

    connection = open_gold_from(gold_source)
    try:
        return build_dispatch(template, record, cleaned, connection)
    finally:
        connection.close()


def render_against_fixtures(source, gold_directory=FIXTURE_GOLD_DIRECTORY,
                            lookups_directory=FIXTURE_LOOKUPS_DIRECTORY):
    """Build and render a template for every sample property set, keeping a sample of the first."""
    renders = []

    for index, property_values in enumerate(sample_property_sets(source.template)):
        built = build_against_fixtures(source.template, property_values, gold_directory, lookups_directory)
        rendered = render_dispatch(built, source.layout_text, FIXTURE_BROWSER_URL, False)
        log(f'rendered {source.template.id} with {built.property_values}')
        renders.append(rendered)

        # The first property set stands as the email's sample
        is_first = index == 0
        if is_first:
            source.sample_html = render_email_sample(built, source.layout_text)
    return renders


# ---------------------------------------------------------------- #
# Step 3: section samples
# ---------------------------------------------------------------- #

def first_use_of(sources, type_name):
    """The first template section using a section type, so its sample shows real settings."""
    for source in sources:
        for section in source.template.sections:
            if section.type == type_name:
                return section.model_dump(mode='json')
    return None


def sample_section_config(sources, type_name):
    """The section config a type's sample is built with: its first real use, else its default params."""
    used = first_use_of(sources, type_name)
    if used is not None:
        return used
    return {'id': type_name, 'type': type_name, 'params': {}}


def section_sample_template(sources):
    """A template that exists only to build one sample of every registered section type."""
    sections = []
    for type_name in sorted(SECTION_TYPES):
        sections.append(sample_section_config(sources, type_name))

    return Template.model_validate({
        'id': 'section_samples',
        'schema_version': max(SUPPORTED_SCHEMA_VERSIONS),
        'name': 'Section samples',
        'description': 'Builds one sample of every section type.',
        'subject': '{template_name}',
        'layout_path': email_layout_path('section_samples'),
        'required_properties': [
            {'key': 'start_date', 'label': 'Data from', 'type': 'date'},
            {'key': 'end_date', 'label': 'Data to', 'type': 'date'},
            {'key': 'jurisdiction', 'label': 'Jurisdiction', 'type': 'enum', 'options': ['federal', 'state']},
            {'key': 'state', 'label': 'State', 'type': 'enum', 'options': [SECTION_SAMPLE_STATE]},
        ],
        'globals': {'include': {}, 'exclude': {}},
        'sections': sections,
    })


def read_partial_source(section_module):
    """The text of a section type's partial, read from beside its module."""
    module_directory = os.path.dirname(os.path.abspath(section_module.__file__))
    partial_path = os.path.join(module_directory, section_module.PARTIAL)
    with open(partial_path, encoding='utf-8') as partial_file:
        return partial_file.read()


def render_section_samples(sources, gold_directory=FIXTURE_GOLD_DIRECTORY,
                           lookups_directory=FIXTURE_LOOKUPS_DIRECTORY):
    """Build every section type once over the fixtures and render each on its own."""
    template = section_sample_template(sources)
    property_values = {
        'start_date': FIXTURE_START_DATE,
        'end_date': FIXTURE_END_DATE,
        'jurisdiction': SECTION_SAMPLE_JURISDICTION,
        'state': SECTION_SAMPLE_STATE,
    }
    built = build_against_fixtures(template, property_values, gold_directory, lookups_directory)

    # One sample per type, beside the source of the partial it was rendered from
    samples = {}
    for built_section in built.sections:
        type_name = built_section.config.type
        samples[type_name] = SectionSample(
            type_name=type_name,
            partial_source=read_partial_source(built_section.module),
            sample_html=render_section_sample(built_section),
        )
        log(f'rendered the {type_name} sample')
    return samples


# ---------------------------------------------------------------- #
# Steps 4 and 5: upload and upsert
# ---------------------------------------------------------------- #

def publish_template(source, bucket, store, published_at, build_tag):
    """Upload a template's layout and sample, then write its template document."""
    template_id = source.template.id
    bucket.upload(email_layout_path(template_id), source.layout_text, JINJA_CONTENT_TYPE)
    bucket.upload(email_sample_path(template_id), source.sample_html, HTML_CONTENT_TYPE)

    # The template as validated, plus where and when it was published
    document = source.template.model_dump(mode='json')
    document['published_at'] = published_at
    document['build_tag'] = build_tag
    document['sample_path'] = email_sample_path(template_id)
    store.upsert_template(template_id, document)
    log(f'published {template_id}')


def publish_section_files(section_samples, bucket):
    """Upload each section type's partial copy and sample."""
    for type_name in sorted(section_samples):
        sample = section_samples[type_name]
        section_module = SECTION_TYPES[type_name]
        partial_path = section_partial_path(type_name, section_module.PARTIAL)
        bucket.upload(partial_path, sample.partial_source, JINJA_CONTENT_TYPE)
        bucket.upload(section_sample_path(type_name), sample.sample_html, HTML_CONTENT_TYPE)
    log('uploaded the section partials and samples')


# ---------------------------------------------------------------- #
# Step 6: the catalogue
# ---------------------------------------------------------------- #

def template_schema_document(sources, generated_at, build_tag):
    """The catalogue document describing how to write a template."""
    placeholders = []
    for name in SUBJECT_PLACEHOLDERS:
        placeholders.append({'name': name, 'description': SUBJECT_PLACEHOLDER_DESCRIPTIONS[name]})

    # The first template in the repository serves as the annotated example
    example = None
    example_sample_path = None
    if sources:
        example = sources[0].raw
        example_sample_path = email_sample_path(sources[0].template.id)

    return {
        'generated_at': generated_at,
        'build_tag': build_tag,
        'supported_schema_versions': sorted(SUPPORTED_SCHEMA_VERSIONS),
        'template_json_schema': json.dumps(Template.model_json_schema()),
        'filter_registry': catalogue_entries(),
        'property_types': list(PROPERTY_TYPES),
        'subject_placeholders': placeholders,
        'authoring_rules': list(AUTHORING_RULES),
        'example_template': example,
        'example_notes': list(EXAMPLE_NOTES),
        'example_sample_path': example_sample_path,
        'sample_notice': SAMPLE_NOTICE,
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


def section_type_entry(sources, type_name):
    """One section type's catalogue entry: what it is, its params, its uses, and where its files are."""
    section_module = SECTION_TYPES[type_name]
    params_schema = section_module.Params.model_json_schema()

    return {
        'type': type_name,
        'description': section_module.DESCRIPTION,
        'renders': section_module.RENDERS,
        'partial': section_module.PARTIAL,
        'params_json_schema': json.dumps(params_schema),
        'used_by': section_uses(sources, type_name),
        'partial_path': section_partial_path(type_name, section_module.PARTIAL),
        'sample_path': section_sample_path(type_name),
    }


def section_types_document(sources, generated_at, build_tag):
    """The catalogue document describing every registered section type."""
    types = []
    for type_name in sorted(SECTION_TYPES):
        types.append(section_type_entry(sources, type_name))

    return {
        'generated_at': generated_at,
        'build_tag': build_tag,
        'sample_notice': SAMPLE_NOTICE,
        'section_types': types,
    }


def write_catalogue(sources, store, generated_at, build_tag):
    """Write both catalogue documents."""
    schema_document = template_schema_document(sources, generated_at, build_tag)
    store.write_catalogue(CATALOGUE_TEMPLATE_SCHEMA_DOCUMENT, schema_document)

    types_document = section_types_document(sources, generated_at, build_tag)
    store.write_catalogue(CATALOGUE_SECTION_TYPES_DOCUMENT, types_document)
    log('wrote the catalogue')


# ---------------------------------------------------------------- #
# The command
# ---------------------------------------------------------------- #

def prepare(templates_directory, only_template_id=None):
    """Steps 1 to 3: validate and render everything, writing nothing."""
    # Every template is validated and rendered, because the catalogue describes them all
    all_sources = load_template_sources(templates_directory)
    if not all_sources:
        log('no templates found')
    for source in all_sources:
        render_against_fixtures(source)

    # Only the template asked for is published, when one was named
    sources = []
    for source in all_sources:
        is_other_template = only_template_id is not None and source.template.id != only_template_id
        if is_other_template:
            continue
        sources.append(source)

    section_samples = render_section_samples(all_sources)
    return PublishPlan(sources=sources, all_sources=all_sources, section_samples=section_samples)


def publish(only_template_id=None, dry_run=False, bucket=None, store=None,
            templates_directory=TEMPLATES_DIRECTORY, build_tag=DRY_RUN_BUILD_TAG):
    """Run every step, or steps 1 to 3 on a dry run. Returns the template sources handled."""
    plan = prepare(templates_directory, only_template_id)

    if dry_run:
        log('dry run: nothing published')
        return plan.sources

    # Steps 4 and 5 for each template, then the section files
    published_at = datetime.datetime.now(datetime.timezone.utc)
    for source in plan.sources:
        publish_template(source, bucket, store, published_at, build_tag)
    publish_section_files(plan.section_samples, bucket)

    # Step 6
    write_catalogue(plan.all_sources, store, published_at, build_tag)
    log(f'published build {build_tag}')
    return plan.sources


def parse_arguments(arguments):
    """Read the command line."""
    parser = argparse.ArgumentParser(description='Validate and publish Dispatch templates.')
    parser.add_argument('--template', default=None, help='Publish only this template id.')
    parser.add_argument('--dry-run', action='store_true', help='Validate and render only.')
    parser.add_argument('--build-tag', default=None,
                        help='The deployed image\'s build tag, stamped on everything published.')
    return parser.parse_args(arguments)


def refuse_local_publish(options):
    """The reason a real publish cannot run here, or None when it can."""
    if not running_in_cloud_run():
        return ('a real publish runs only inside the deployed image. '
                'Use --dry-run locally; deploy/deploy.sh deploy publishes.')
    if options.build_tag is None:
        return 'a real publish needs --build-tag, the tag of the image it runs in'
    return None


def main(arguments=None):
    """Run publish-templates and return the exit code."""
    options = parse_arguments(arguments)

    # A dry run needs no cloud access
    if options.dry_run:
        publish(options.template, dry_run=True)
        return 0

    # A real publish must come from the deployed image
    refusal = refuse_local_publish(options)
    if refusal is not None:
        log(f'refused: {refusal}')
        return 2

    from dispatch.delivery.archive import GcsArchiveStore
    from dispatch.store.firestore import FirestoreDispatchStore
    bucket = GcsArchiveStore()
    store = FirestoreDispatchStore()
    publish(options.template, bucket=bucket, store=store, build_tag=options.build_tag)
    return 0


if __name__ == '__main__':
    sys.exit(main())
