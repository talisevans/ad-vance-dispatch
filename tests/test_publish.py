"""
publish-templates tests: a dry run validates and renders against the fixtures
and publishes nothing; a full run uploads the layout, upserts the template and
writes both catalogue documents, and the job runs against what it wrote.
"""

import json
import os
import shutil

import pytest

from dispatch.delivery.archive import FakeArchiveStore
from dispatch.publish_templates import publish, sample_property_sets
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


def test_full_publish_writes_layout_template_and_catalogue(templates_directory):
    """A full publish uploads the layout, upserts the template and writes both catalogue documents."""
    bucket = FakeArchiveStore()
    store = FakeDispatchStore()
    publish(bucket=bucket, store=store, templates_directory=templates_directory)

    assert list(bucket.objects) == [f'templates/{PROBE_TEMPLATE_ID}/layout.html.j2']
    assert store.templates[PROBE_TEMPLATE_ID]['schema_version'] == 1
    assert 'published_at' in store.templates[PROBE_TEMPLATE_ID]

    schema = store.catalogue['template_schema']
    assert schema['example_template']['id'] == PROBE_TEMPLATE_ID
    keys = []
    for entry in schema['filter_registry']:
        keys.append(entry['key'])
    assert 'classification' in keys
    assert 'platform' in keys

    # Find the probe's entry among every registered type
    section_types = store.catalogue['section_types']['section_types']
    entries_by_type = {}
    for entry in section_types:
        entries_by_type[entry['type']] = entry
    assert set(entries_by_type) == {'bias_gauge', 'cumulative_spend', 'messaging_tone', 'top_seats', 'probe'}

    used_by_ids = []
    for use in entries_by_type['probe']['used_by']:
        used_by_ids.append(use['section_id'])
    assert used_by_ids == ['statewide', 'participants']

    # A real type no template here uses is still catalogued, with its params schema
    assert entries_by_type['top_seats']['used_by'] == []
    assert 'rank_by_window' in entries_by_type['top_seats']['params_json_schema']


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
    publish(bucket=FakeArchiveStore(), store=services.store, templates_directory=templates_directory)
    assert 'published_at' in services.store.templates[PROBE_TEMPLATE_ID]

    report = run_record(RunRequest(record_id=RECORD_ID), services)
    assert report.exit_code == SUCCESS_EXIT_CODE
    assert report.outcome == 'sent'
