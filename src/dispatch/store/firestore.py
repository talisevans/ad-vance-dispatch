"""
Every Firestore read and write the job and publish-templates make.

`DispatchStore` is the seam: `FirestoreDispatchStore` talks to the default
database, `FakeDispatchStore` keeps documents in memory for tests. Documents
cross the seam as plain dictionaries; the models in `dispatch.models` parse
them.

Ledger recipients are keyed by email address, and an address holds dots, so
the ledger is always written with `set(..., merge=True)` and a nested map
rather than with dotted field paths.
"""

import copy

from dispatch.config import (
    CATALOGUE_COLLECTION,
    FIRESTORE_DATABASE,
    PROJECT_ID,
    RECORDS_COLLECTION,
    RUNS_SUBCOLLECTION,
    TEMPLATES_COLLECTION,
)


# ---------------------------------------------------------------- #
# The seam
# ---------------------------------------------------------------- #

class DispatchStore:
    """Reads and writes Dispatch documents."""

    def get_record(self, record_id):
        """The record document with its `id` added, or None when it does not exist."""
        raise NotImplementedError

    def get_template(self, template_id):
        """The template document, or None when it does not exist."""
        raise NotImplementedError

    def read_ledger(self, record_id, slot):
        """The ledger document for a slot, or None when the slot has not run."""
        raise NotImplementedError

    def merge_ledger(self, record_id, slot, fields):
        """Merge fields into a slot's ledger, creating it when needed."""
        raise NotImplementedError

    def write_last_run(self, record_id, last_run):
        """Replace the record's `last_run` map."""
        raise NotImplementedError

    def upsert_template(self, template_id, document):
        """Write a template document in full."""
        raise NotImplementedError

    def write_catalogue(self, document_name, document):
        """Write one catalogue document in full."""
        raise NotImplementedError


# ---------------------------------------------------------------- #
# Firestore
# ---------------------------------------------------------------- #

class FirestoreDispatchStore(DispatchStore):
    """The default Firestore database."""

    def __init__(self, client=None):
        """Remember a Firestore client, or make one on first use."""
        self.firestore_client = client

    def client(self):
        """The Firestore client for the default database."""
        if self.firestore_client is None:
            from google.cloud import firestore
            self.firestore_client = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DATABASE)
        return self.firestore_client

    def record_reference(self, record_id):
        """The document reference for one record."""
        collection = self.client().collection(RECORDS_COLLECTION)
        return collection.document(record_id)

    def ledger_reference(self, record_id, slot):
        """The document reference for one slot's ledger."""
        record_reference = self.record_reference(record_id)
        return record_reference.collection(RUNS_SUBCOLLECTION).document(slot)

    def get_record(self, record_id):
        """Read the record, adding its id."""
        snapshot = self.record_reference(record_id).get()
        if not snapshot.exists:
            return None
        document = snapshot.to_dict()
        document['id'] = snapshot.id
        return document

    def get_template(self, template_id):
        """Read the template document."""
        collection = self.client().collection(TEMPLATES_COLLECTION)
        snapshot = collection.document(template_id).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()

    def read_ledger(self, record_id, slot):
        """Read a slot's ledger."""
        snapshot = self.ledger_reference(record_id, slot).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()

    def merge_ledger(self, record_id, slot, fields):
        """Merge into a slot's ledger with nested maps, never dotted paths."""
        self.ledger_reference(record_id, slot).set(fields, merge=True)

    def write_last_run(self, record_id, last_run):
        """Replace `last_run` on the record, leaving every other field alone."""
        self.record_reference(record_id).update({'last_run': last_run})

    def upsert_template(self, template_id, document):
        """Write the template document in full."""
        collection = self.client().collection(TEMPLATES_COLLECTION)
        collection.document(template_id).set(document)

    def write_catalogue(self, document_name, document):
        """Write a catalogue document in full."""
        collection = self.client().collection(CATALOGUE_COLLECTION)
        collection.document(document_name).set(document)


# ---------------------------------------------------------------- #
# In memory, for tests
# ---------------------------------------------------------------- #

def deep_merge(target, fields):
    """Merge nested dictionaries into a target in place, as Firestore's merge does."""
    for key, value in fields.items():
        existing = target.get(key)
        both_maps = isinstance(existing, dict) and isinstance(value, dict)
        if both_maps:
            deep_merge(existing, value)
        else:
            target[key] = copy.deepcopy(value)


class FakeDispatchStore(DispatchStore):
    """Documents in dictionaries, with the same merge rules as Firestore."""

    def __init__(self, records=None, templates=None):
        """Start with the given records and templates, keyed by id."""
        self.records = copy.deepcopy(records or {})
        self.templates = copy.deepcopy(templates or {})
        self.ledgers = {}
        self.catalogue = {}

    def get_record(self, record_id):
        """A copy of the record with its id."""
        record = self.records.get(record_id)
        if record is None:
            return None
        document = copy.deepcopy(record)
        document['id'] = record_id
        return document

    def get_template(self, template_id):
        """A copy of the template."""
        template = self.templates.get(template_id)
        if template is None:
            return None
        return copy.deepcopy(template)

    def read_ledger(self, record_id, slot):
        """A copy of a slot's ledger."""
        ledger = self.ledgers.get((record_id, slot))
        if ledger is None:
            return None
        return copy.deepcopy(ledger)

    def merge_ledger(self, record_id, slot, fields):
        """Merge into a slot's ledger."""
        ledger = self.ledgers.setdefault((record_id, slot), {})
        deep_merge(ledger, fields)

    def write_last_run(self, record_id, last_run):
        """Replace `last_run` on the stored record."""
        self.records[record_id]['last_run'] = copy.deepcopy(last_run)

    def upsert_template(self, template_id, document):
        """Store the template."""
        self.templates[template_id] = copy.deepcopy(document)

    def write_catalogue(self, document_name, document):
        """Store a catalogue document."""
        self.catalogue[document_name] = copy.deepcopy(document)
