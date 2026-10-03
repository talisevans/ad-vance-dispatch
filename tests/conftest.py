"""
Shared test fixtures: the fixture gold connection, the test-only probe section,
a probe template and record, and a set of fake services for whole runs.
"""

import datetime
import os
import shutil

import pytest

from dispatch.data.gold import LocalGoldSource, open_gold_from
from dispatch.data.reference import ReferenceData
from dispatch.delivery.archive import FakeArchiveStore
from dispatch.delivery.ses import FakeMailer
from dispatch.render.layout import LocalLayoutStore
from dispatch.run import Services
from dispatch.scheduling.scheduler import FakeSchedulerClient
from dispatch.sections.registry import SECTION_TYPES
from dispatch.store.firestore import FakeDispatchStore
from tests.support import probe_section


# ---------------------------------------------------------------- #
# Paths
# ---------------------------------------------------------------- #

TESTS_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
FIXTURE_GOLD_DIRECTORY = os.path.join(TESTS_DIRECTORY, 'fixtures', 'gold')
FIXTURE_LOOKUPS_DIRECTORY = os.path.join(TESTS_DIRECTORY, 'fixtures', 'lookups')
PROBE_LAYOUT_PATH = os.path.join(TESTS_DIRECTORY, 'support', 'probe_layout.html.j2')

# The probe template's id and its layout's path inside a layouts root
PROBE_TEMPLATE_ID = 'probe_brief'
PROBE_LAYOUT_RELATIVE_PATH = f'templates/emails/{PROBE_TEMPLATE_ID}/layout.html.j2'

# The record every run test uses
RECORD_ID = 'record_vic'
RECIPIENTS = ['alice@example.test', 'bob@example.test', 'carol@example.test']

# Monday 5 October 2026 at 09:00 in Melbourne (daylight saving), as UTC
MONDAY_NINE_AM_MELBOURNE = datetime.datetime(2026, 10, 4, 22, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------- #
# Gold
# ---------------------------------------------------------------- #

@pytest.fixture
def gold_source():
    """The fixture gold, read in place."""
    return LocalGoldSource(FIXTURE_GOLD_DIRECTORY, FIXTURE_LOOKUPS_DIRECTORY)


@pytest.fixture
def gold_connection(gold_source):
    """An open DuckDB connection over the fixture gold."""
    connection = open_gold_from(gold_source)
    yield connection
    connection.close()


@pytest.fixture
def reference(gold_connection):
    """Reference data read from the fixture lookups."""
    return ReferenceData.load(gold_connection)


# ---------------------------------------------------------------- #
# The probe section, template and record
# ---------------------------------------------------------------- #

@pytest.fixture
def registered_probe():
    """Register the probe section type for one test, then remove it."""
    SECTION_TYPES[probe_section.TYPE_NAME] = probe_section
    yield probe_section
    SECTION_TYPES.pop(probe_section.TYPE_NAME, None)


def probe_template_document():
    """A template shaped like the Weekly Campaign Brief, built from probe sections."""
    return {
        'id': PROBE_TEMPLATE_ID,
        'schema_version': 1,
        'name': 'Probe Brief',
        'description': 'A test template.',
        'subject': '{jurisdiction_label} probe brief, week to {as_of_long}',
        'layout_path': PROBE_LAYOUT_RELATIVE_PATH,
        'required_properties': [
            {'key': 'start_date', 'label': 'Data from', 'type': 'date'},
            {'key': 'end_date', 'label': 'Data to', 'type': 'date'},
            {'key': 'jurisdiction', 'label': 'Jurisdiction', 'type': 'enum', 'options': ['federal', 'state']},
            {'key': 'state', 'label': 'State', 'type': 'enum',
             'options': ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT'],
             'required_when': {'jurisdiction': 'state'}},
        ],
        'globals': {'include': {}, 'exclude': {'classification': ['government']}},
        'sections': [
            {'id': 'statewide', 'type': 'probe', 'params': {'window_days': 7}},
            {'id': 'participants', 'type': 'probe', 'params': {'window_days': 7},
             'include': {'classification': ['political participant']}},
        ],
    }


def record_document(**overrides):
    """A Victorian state record sending weekly on Mondays at 09:00 Melbourne time."""
    document = {
        'name': 'VIC probe brief',
        'template_id': PROBE_TEMPLATE_ID,
        'template_schema_version': 1,
        'property_values': {
            'start_date': '2026-08-01',
            'end_date': '2026-11-28',
            'jurisdiction': 'state',
            'state': 'VIC',
        },
        'recipients': list(RECIPIENTS),
        'contact_email': None,
        'schedule': {'preset': 'weekly', 'days': ['mon'], 'time': '09:00'},
        'cron': '0 9 * * 1',
        'timezone': 'Australia/Melbourne',
        'start_delivery': '2026-10-01',
        'end_delivery': '2026-11-28',
        'status': 'active',
        'created_by': 'admin@example.test',
    }
    document.update(overrides)
    return document


@pytest.fixture
def layouts_root(tmp_path):
    """A layouts root holding the probe template's layout at its published path."""
    target = tmp_path / PROBE_LAYOUT_RELATIVE_PATH
    target.parent.mkdir(parents=True)
    shutil.copyfile(PROBE_LAYOUT_PATH, target)
    return str(tmp_path)


class FixedClock:
    """A clock that returns a set time and can be moved forward."""

    def __init__(self, now):
        """Start at the given time."""
        self.now = now

    def __call__(self):
        """The current fixed time."""
        return self.now

    def advance(self, **delta):
        """Move the clock forward by a timedelta's keyword arguments."""
        self.now = self.now + datetime.timedelta(**delta)


@pytest.fixture
def make_services(gold_source, layouts_root, registered_probe):
    """A factory for fake services around one record and the probe template."""

    def factory(record_overrides=None, failing_recipients=(), now=MONDAY_NINE_AM_MELBOURNE):
        """Build fake services with the record changed as asked."""
        overrides = record_overrides or {}
        store = FakeDispatchStore(
            records={RECORD_ID: record_document(**overrides)},
            templates={PROBE_TEMPLATE_ID: probe_template_document()},
        )
        return Services(
            store=store,
            layouts=LocalLayoutStore(layouts_root),
            gold_source=gold_source,
            archive=FakeArchiveStore(),
            mailer=FakeMailer(failing_recipients),
            scheduler=FakeSchedulerClient([f'dispatch-{RECORD_ID}']),
            clock=FixedClock(now),
        )

    return factory
