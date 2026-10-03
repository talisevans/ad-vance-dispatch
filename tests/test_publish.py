"""
publish-templates tests: a dry run validates and renders against the fixtures
and publishes nothing; a full run uploads layouts, partial copies and samples,
upserts the template, writes both catalogue documents stamped with the build
tag, and the job runs against what it wrote. A real publish outside Cloud Run
is refused.
"""

import json
import os
import shutil

import pytest

from dispatch.delivery.archive import FakeArchiveStore
from dispatch.publish_templates import main as publish_main
from dispatch.publish_templates import publish, sample_property_sets
from dispatch.render.samples import SAMPLE_NOTICE
from dispatch.models.template import Template
from dispatch.run import SUCCESS_EXIT_CODE, RunRequest, run_record
from dispatch.store.firestore import FakeDispatchStore
from tests.conftest import PROBE_LAYOUT_PATH, PROBE_TEMPLATE_ID, RECORD_ID, probe_template_document


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

@pytest.fixture
def templates_directory(tmp_path, registered_probe):
    """A templates folder holding the probe template and its layout."""
    template_directory = tmp_path / PROBE_TEMPLATE_ID
    template_directory.mkdir()
    with open(template_directory / 'template.json', 'w', encoding='utf-8') as template_file:
        json.dump(probe_template_document(), template_file)
    shutil.copyfile(PROBE_LAYOUT_PATH, template_directory / 'layout.html.j2')
    return str(tmp_path)


# The build tag the full publishes in these tests stamp
BUILD_TAG = 'abc1234-20261004T000000Z'

# The four real section types, which every publish samples
REAL_SECTION_TYPES = ['bias_gauge', 'cumulative_spend', 'messaging_tone', 'top_seats']


def full_publish(templates_directory, store=None):
    """Run a full publish into fakes and return the bucket and the store."""
    bucket = FakeArchiveStore()
    if store is None:
        store = FakeDispatchStore()
    publish(bucket=bucket, store=store, templates_directory=templates_directory, build_tag=BUILD_TAG)
    return bucket, store


def uploaded_text(bucket, object_path):
    """The text uploaded to one bucket path."""
    data, _content_type = bucket.objects[object_path]
    return data


# ---------------------------------------------------------------- #
# Tests
# ---------------------------------------------------------------- #

def test_sample_property_sets_cover_each_branch(registered_probe):
    """One federal sample and one state sample, so both branches render."""
    template = Template.model_validate(probe_template_document())
    samples = sample_property_sets(template)
    jurisdictions = []
    for sample in samples:
        jurisdictions.append(sample['jurisdiction'])
    assert jurisdictions == ['federal', 'state']
    assert samples[1]['state'] == 'NSW'


def test_dry_run_validates_renders_and_publishes_nothing(templates_directory):
    """A dry run touches neither the bucket nor Firestore."""
    bucket = FakeArchiveStore()
    store = FakeDispatchStore()
    sources = publish(dry_run=True, bucket=bucket, store=store, templates_directory=templates_directory)

    assert len(sources) == 1
    assert bucket.objects == {}
    assert store.templates == {}
    assert store.catalogue == {}


def test_full_publish_uploads_layouts_partials_and_samples(templates_directory):
    """A full publish fills templates/emails/ and templates/sections/ in the bucket."""
    bucket, _store = full_publish(templates_directory)

    # The probe email template's layout and sample
    expected = {
        f'templates/emails/{PROBE_TEMPLATE_ID}/layout.html.j2',
        f'templates/emails/{PROBE_TEMPLATE_ID}/sample.html',
    }

    # Each registered section type's partial copy and sample
    for type_name in REAL_SECTION_TYPES:
        expected.add(f'templates/sections/{type_name}/{type_name}.html.j2')
        expected.add(f'templates/sections/{type_name}/sample.html')
    expected.add('templates/sections/probe/probe.html.j2')
    expected.add('templates/sections/probe/sample.html')
    assert set(bucket.objects) == expected


def test_samples_carry_the_notice_and_describe_charts(templates_directory):
    """Every sample says its figures are made up, and has no images left in it."""
    bucket, _store = full_publish(templates_directory)

    for object_path in bucket.objects:
        if not object_path.endswith('sample.html'):
            continue
        sample = uploaded_text(bucket, object_path)
        assert SAMPLE_NOTICE in sample
        assert '<img' not in sample
        assert 'data:image' not in sample

    # The gauge's chart is described in words instead
    gauge_sample = uploaded_text(bucket, 'templates/sections/bias_gauge/sample.html')
    assert '[Chart, ' in gauge_sample


def test_partial_copy_matches_the_partial_in_the_package(templates_directory):
    """The bucket's partial copy is the partial file the job renders with."""
    from dispatch.sections.top_seats import top_seats

    bucket, _store = full_publish(templates_directory)
    partial_file_path = os.path.join(os.path.dirname(top_seats.__file__), 'top_seats.html.j2')
    with open(partial_file_path, encoding='utf-8') as partial_file:
        partial_text = partial_file.read()
    assert uploaded_text(bucket, 'templates/sections/top_seats/top_seats.html.j2') == partial_text


def test_full_publish_writes_template_and_catalogue(templates_directory):
    """A full publish upserts the template and writes both catalogue documents with the build tag."""
    _bucket, store = full_publish(templates_directory)

    template_document = store.templates[PROBE_TEMPLATE_ID]
    assert template_document['schema_version'] == 1
    assert 'published_at' in template_document
    assert template_document['build_tag'] == BUILD_TAG
    assert template_document['sample_path'] == f'templates/emails/{PROBE_TEMPLATE_ID}/sample.html'

    schema = store.catalogue['template_schema']
    assert schema['build_tag'] == BUILD_TAG
    assert schema['example_template']['id'] == PROBE_TEMPLATE_ID
    assert schema['example_sample_path'] == f'templates/emails/{PROBE_TEMPLATE_ID}/sample.html'
    assert 'example_sample_html' not in schema
    keys = []
    for entry in schema['filter_registry']:
        keys.append(entry['key'])
    assert 'classification' in keys
    assert 'platform' in keys

    # Find each type's entry among every registered type
    section_types_document = store.catalogue['section_types']
    assert section_types_document['build_tag'] == BUILD_TAG
    entries_by_type = {}
    for entry in section_types_document['section_types']:
        entries_by_type[entry['type']] = entry
    assert set(entries_by_type) == set(REAL_SECTION_TYPES) | {'probe'}

    used_by_ids = []
    for use in entries_by_type['probe']['used_by']:
        used_by_ids.append(use['section_id'])
    assert used_by_ids == ['statewide', 'participants']

    # A real type no template here uses is still catalogued, naming its files by bucket path only
    top_seats_entry = entries_by_type['top_seats']
    assert top_seats_entry['used_by'] == []
    assert 'rank_by_window' in top_seats_entry['params_json_schema']
    assert top_seats_entry['sample_path'] == 'templates/sections/top_seats/sample.html'
    assert top_seats_entry['partial_path'] == 'templates/sections/top_seats/top_seats.html.j2'
    assert 'sample_html' not in top_seats_entry
    assert 'partial_source' not in top_seats_entry


def test_catalogue_paths_name_uploaded_files(templates_directory):
    """Every path the catalogue names is a file the same publish uploaded."""
    bucket, store = full_publish(templates_directory)

    named_paths = [store.catalogue['template_schema']['example_sample_path']]
    for entry in store.catalogue['section_types']['section_types']:
        named_paths.append(entry['sample_path'])
        named_paths.append(entry['partial_path'])

    for object_path in named_paths:
        assert object_path in bucket.objects


def test_real_publish_is_refused_outside_cloud_run(templates_directory, monkeypatch):
    """Without Cloud Run's CLOUD_RUN_JOB variable, a real publish stops before touching anything."""
    monkeypatch.delenv('CLOUD_RUN_JOB', raising=False)
    exit_code = publish_main(['--build-tag', BUILD_TAG])
    assert exit_code == 2


def test_real_publish_needs_a_build_tag(monkeypatch):
    """Inside Cloud Run, a real publish without a build tag is refused."""
    monkeypatch.setenv('CLOUD_RUN_JOB', 'advance-dispatch')
    exit_code = publish_main([])
    assert exit_code == 2


def test_folder_must_match_template_id(templates_directory):
    """A template whose id differs from its folder is refused."""
    os.rename(os.path.join(templates_directory, PROBE_TEMPLATE_ID), os.path.join(templates_directory, 'renamed'))
    with pytest.raises(ValueError):
        publish(dry_run=True, templates_directory=templates_directory)


def test_the_job_runs_against_what_publish_wrote(templates_directory, make_services):
    """A record runs and sends against the template document publish-templates actually wrote."""
    services = make_services()

    # Replace the store's template with the one a full publish writes
    del services.store.templates[PROBE_TEMPLATE_ID]
    full_publish(templates_directory, store=services.store)
    assert services.store.templates[PROBE_TEMPLATE_ID]['build_tag'] == BUILD_TAG

    report = run_record(RunRequest(record_id=RECORD_ID), services)
    assert report.exit_code == SUCCESS_EXIT_CODE
    assert report.outcome == 'sent'
