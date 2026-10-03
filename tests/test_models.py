"""
Model tests: template validation (schema version, section types and params,
subject placeholders, required_when) and record validation.
"""

import copy

import pytest
from pydantic import ValidationError

from dispatch.models.ledger import RecipientOutcome, RunLedger
from dispatch.models.record import DispatchRecord
from dispatch.models.template import PropertyValuesError, Template
from tests.conftest import probe_template_document, record_document


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

def changed_template(change):
    """The probe template document after a change function has edited it."""
    document = copy.deepcopy(probe_template_document())
    change(document)
    return document


def valid_values(**overrides):
    """Property values for a Victorian state record."""
    values = {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'state',
        'state': 'VIC',
    }
    values.update(overrides)
    return values


# ---------------------------------------------------------------- #
# Templates
# ---------------------------------------------------------------- #

def test_probe_template_is_valid(registered_probe):
    """The probe template validates and its sections parse their params."""
    template = Template.model_validate(probe_template_document())
    assert template.sections[0].parsed_params().window_days == 7
    assert template.globals.exclude == {'classification': ['government']}


def test_unsupported_schema_version_is_refused(registered_probe):
    """A template from a newer schema is refused."""
    document = changed_template(lambda template: template.update(schema_version=2))
    with pytest.raises(ValidationError) as caught:
        Template.model_validate(document)
    assert 'schema_version 2 is not supported' in str(caught.value)


def test_unknown_section_type_is_refused(registered_probe):
    """A section naming a type nobody registered fails at publish time."""
    def rename_type(template):
        """Point the first section at an unknown type."""
        template['sections'][0]['type'] = 'no_such_section'

    with pytest.raises(ValidationError) as caught:
        Template.model_validate(changed_template(rename_type))
    assert 'unknown section type "no_such_section"' in str(caught.value)


def test_section_params_typo_is_refused(registered_probe):
    """A misspelt param fails against the section type's own model."""
    def misspell(template):
        """Misspell a param on the first section."""
        template['sections'][0]['params'] = {'window_dayz': 7}

    with pytest.raises(ValidationError) as caught:
        Template.model_validate(changed_template(misspell))
    assert 'section "statewide" (probe) has invalid params' in str(caught.value)


def test_section_filters_are_checked(registered_probe):
    """A section filter naming a weight key is refused."""
    def add_weight_key(template):
        """Give the second section a weight-key filter."""
        template['sections'][1]['include'] = {'gender': ['female']}

    with pytest.raises(ValidationError) as caught:
        Template.model_validate(changed_template(add_weight_key))
    assert 'gender' in str(caught.value)


def test_duplicate_section_ids_are_refused(registered_probe):
    """Section ids must be unique within a template."""
    def duplicate(template):
        """Give both sections the same id."""
        template['sections'][1]['id'] = 'statewide'

    with pytest.raises(ValidationError) as caught:
        Template.model_validate(changed_template(duplicate))
    assert 'section id "statewide" appears more than once' in str(caught.value)


def test_unknown_subject_placeholder_is_refused(registered_probe):
    """Only the documented subject placeholders are allowed."""
    document = changed_template(lambda template: template.update(subject='Brief for {recipient_name}'))
    with pytest.raises(ValidationError) as caught:
        Template.model_validate(document)
    assert 'unknown subject placeholder "{recipient_name}"' in str(caught.value)


def test_required_when_must_name_a_real_option(registered_probe):
    """required_when on an enum must name one of its options."""
    def bad_condition(template):
        """Make state depend on an option jurisdiction does not have."""
        template['required_properties'][3]['required_when'] = {'jurisdiction': 'international'}

    with pytest.raises(ValidationError):
        Template.model_validate(changed_template(bad_condition))


def test_template_ids_are_slugs(registered_probe):
    """A template id with spaces or capitals is refused."""
    document = changed_template(lambda template: template.update(id='Weekly Brief'))
    with pytest.raises(ValidationError):
        Template.model_validate(document)


# ---------------------------------------------------------------- #
# Property values
# ---------------------------------------------------------------- #

def test_valid_state_values(registered_probe):
    """A state record with a state passes and keeps every value."""
    template = Template.model_validate(probe_template_document())
    assert template.validate_property_values(valid_values()) == valid_values()


def test_state_is_required_for_a_state_record(registered_probe):
    """required_when: a state record must name its state."""
    template = Template.model_validate(probe_template_document())
    values = valid_values()
    del values['state']
    with pytest.raises(PropertyValuesError) as caught:
        template.validate_property_values(values)
    assert caught.value.problems == ['"state" is required']


def test_state_is_optional_for_a_federal_record(registered_probe):
    """A federal record may leave state out."""
    template = Template.model_validate(probe_template_document())
    without_state = valid_values(jurisdiction='federal')
    del without_state['state']
    assert 'state' not in template.validate_property_values(without_state)


def test_state_on_a_federal_record_is_kept(registered_probe):
    """A state supplied on a federal record is kept, so the Dispatch narrows to that state."""
    template = Template.model_validate(probe_template_document())
    federal_victoria = valid_values(jurisdiction='federal')
    assert template.validate_property_values(federal_victoria) == federal_victoria


def test_state_on_a_federal_record_is_checked(registered_probe):
    """A state supplied on a federal record must still be one of the options."""
    template = Template.model_validate(probe_template_document())
    with pytest.raises(PropertyValuesError) as caught:
        template.validate_property_values(valid_values(jurisdiction='federal', state='Victoria'))
    assert 'state' in caught.value.problems[0]


def test_enum_membership_and_dates_are_checked(registered_probe):
    """A jurisdiction outside the options and a malformed date are both reported."""
    template = Template.model_validate(probe_template_document())
    with pytest.raises(PropertyValuesError) as caught:
        template.validate_property_values(valid_values(jurisdiction='international', start_date='1/8/2026'))
    problems = ' '.join(caught.value.problems)
    assert 'jurisdiction' in problems
    assert 'start_date' in problems


def test_unknown_property_is_refused(registered_probe):
    """A value for a property the template does not declare is a mistake."""
    template = Template.model_validate(probe_template_document())
    with pytest.raises(PropertyValuesError):
        template.validate_property_values(valid_values(colour='red'))


# ---------------------------------------------------------------- #
# Records and ledgers
# ---------------------------------------------------------------- #

def test_record_parses_and_falls_back_to_creator_contact():
    """contact_email null means the record's creator is the contact."""
    document = record_document()
    document['id'] = 'abc'
    record = DispatchRecord.model_validate(document)
    assert record.contact() == 'admin@example.test'
    assert record.trigger_name() == 'dispatch-abc'


def test_record_caps_recipients_at_fifty():
    """Fifty-one recipients is one too many."""
    document = record_document(recipients=[f'person{number}@example.test' for number in range(51)])
    document['id'] = 'abc'
    with pytest.raises(ValidationError):
        DispatchRecord.model_validate(document)


def test_record_refuses_an_unknown_timezone():
    """The timezone must be a real IANA name."""
    document = record_document(timezone='Australia/Gotham')
    document['id'] = 'abc'
    with pytest.raises(ValidationError):
        DispatchRecord.model_validate(document)


def test_ledger_lists_only_unsent_recipients():
    """A ledger with Alice sent and Bob failed leaves Bob and Carol to send."""
    import datetime

    started_at = datetime.datetime(2026, 10, 4, 22, 0, tzinfo=datetime.timezone.utc)
    ledger = RunLedger.start('2026-10-05T09:00', 'scheduled', started_at, '2026-10-01', 'sent/x/')
    ledger.recipients['alice@example.test'] = RecipientOutcome(status='sent', message_id='<1@x>')
    ledger.recipients['bob@example.test'] = RecipientOutcome(status='failed', error='550')

    pending = ledger.recipients_to_send(['alice@example.test', 'bob@example.test', 'carol@example.test'])
    assert pending == ['bob@example.test', 'carol@example.test']
    assert ledger.expire_at == started_at + datetime.timedelta(days=30)
