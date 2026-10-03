"""
The Dispatch Template: what an email contains, which properties a record must
supply, and how each section filters the data.

The shape mirrors `templates/<id>/template.json` and the Firestore document
`dispatch_templates/<id>`. Validation runs in four layers:

  1. Field types, through pydantic.
  2. Filter keys and values, against the filter registry.
  3. Each section's params, against that section type's own `Params` model.
  4. A record's property values, through `Template.validate_property_values`.
"""

import datetime
import string
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dispatch.filters.registry import BOOLEAN_VALUES, check_filter_key


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# Template schema versions this build of the job understands
SUPPORTED_SCHEMA_VERSIONS = {1}

# Template and section ids are readable slugs: lower case, digits and underscores
SLUG_PATTERN = r'^[a-z][a-z0-9_]*$'

# The property types a template may declare in v1
PROPERTY_TYPES = ('date', 'enum', 'string', 'number', 'affiliation_list')

# The placeholders a subject line may use
SUBJECT_PLACEHOLDERS = (
    'jurisdiction_label',
    'as_of_long',
    'window_start_long',
    'template_name',
    'record_name',
)

# A filter value: text, true or false, or null meaning unmapped
FilterValue = Union[bool, str, None]


class PropertyValuesError(ValueError):
    """Raised when a record's property values do not satisfy its template."""

    def __init__(self, problems):
        """Keep every problem found, and say them all in the message."""
        self.problems = problems
        message = 'invalid property values: ' + '; '.join(problems)
        super().__init__(message)


# ---------------------------------------------------------------- #
# Property definitions
# ---------------------------------------------------------------- #

class PropertyDefinition(BaseModel):
    """One property a record must supply: its key, label, type and when it is required."""

    model_config = ConfigDict(extra='forbid')

    key: str = Field(pattern=SLUG_PATTERN)
    label: str
    type: Literal['date', 'enum', 'string', 'number', 'affiliation_list']
    options: Optional[list[str]] = None
    required_when: Optional[dict[str, str]] = None

    @model_validator(mode='after')
    def check_options(self):
        """An enum must list its options; no other type may."""
        is_enum = self.type == 'enum'
        has_options = bool(self.options)
        if is_enum and not has_options:
            raise ValueError(f'enum property "{self.key}" must list its options')
        if not is_enum and self.options is not None:
            raise ValueError(f'only enum properties take options, "{self.key}" is {self.type}')
        return self

    def is_required(self, values):
        """Whether this property must be present, given the other values supplied."""
        if not self.required_when:
            return True

        # Every condition must hold for the property to be required
        for other_key, required_value in self.required_when.items():
            other_value = values.get(other_key)
            if other_value != required_value:
                return False
        return True

    def value_problem(self, value):
        """Return what is wrong with one supplied value, or None when it is fine."""
        # Dates and affiliation lists have their own checks; the rest are checked here by type
        if self.type == 'date':
            return date_problem(self.key, value)
        if self.type == 'enum':
            if value not in self.options:
                allowed = ', '.join(self.options)
                return f'"{self.key}" must be one of {allowed}, got {value!r}'
            return None
        if self.type == 'string':
            if not isinstance(value, str):
                return f'"{self.key}" must be text, got {value!r}'
            return None
        if self.type == 'number':
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not is_number:
                return f'"{self.key}" must be a number, got {value!r}'
            return None
        return affiliation_list_problem(self.key, value)


def date_problem(key, value):
    """Return what is wrong with a date value, or None when it is a `YYYY-MM-DD` string."""
    if not isinstance(value, str):
        return f'"{key}" must be a YYYY-MM-DD date, got {value!r}'
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return f'"{key}" must be a YYYY-MM-DD date, got {value!r}'
    return None


def affiliation_list_problem(key, value):
    """Return what is wrong with an affiliation list, or None when it is a list of ids."""
    if not isinstance(value, list):
        return f'"{key}" must be a list of affiliation ids, got {value!r}'
    for item in value:
        if not isinstance(item, str):
            return f'"{key}" must hold affiliation ids only, got {item!r}'
    return None


# ---------------------------------------------------------------- #
# Filters
# ---------------------------------------------------------------- #

class FilterSet(BaseModel):
    """An `include` and an `exclude` map, each from a filter key to a list of values."""

    model_config = ConfigDict(extra='forbid')

    include: dict[str, list[FilterValue]] = Field(default_factory=dict)
    exclude: dict[str, list[FilterValue]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check_keys_and_values(self):
        """Every key must be registered and implemented, and every list non-empty and well typed."""
        for map_name, filter_map in (('include', self.include), ('exclude', self.exclude)):
            for key, values in filter_map.items():
                filter_key = check_filter_key(key)

                # An empty list is ambiguous, so it is refused
                if len(values) == 0:
                    raise ValueError(f'{map_name}.{key} has an empty value list')

                check_filter_value_types(filter_key, map_name, values)
        return self

    def is_empty(self):
        """Whether this set filters nothing."""
        return not self.include and not self.exclude


def check_filter_value_types(filter_key, map_name, values):
    """Raise ValueError when a value does not match its key's declared type."""
    for value in values:
        if value is None:
            continue
        is_boolean_key = filter_key.value_type == BOOLEAN_VALUES
        if is_boolean_key and not isinstance(value, bool):
            raise ValueError(f'{map_name}.{filter_key.key} takes true or false, got {value!r}')
        if not is_boolean_key and not isinstance(value, str):
            raise ValueError(f'{map_name}.{filter_key.key} takes text, got {value!r}')


# ---------------------------------------------------------------- #
# Sections
# ---------------------------------------------------------------- #

class SectionConfig(BaseModel):
    """One section of a template: its id, its reusable type, its params and its own filters."""

    model_config = ConfigDict(extra='forbid')

    id: str = Field(pattern=SLUG_PATTERN)
    type: str
    params: dict = Field(default_factory=dict)
    include: dict[str, list[FilterValue]] = Field(default_factory=dict)
    exclude: dict[str, list[FilterValue]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check_type_and_params(self):
        """The type must be registered, its params must validate, and its filters must be legal."""
        self.filter_set()
        self.parsed_params()
        return self

    def filter_set(self):
        """This section's own filters as a FilterSet."""
        return FilterSet(include=self.include, exclude=self.exclude)

    def section_type(self):
        """The module that builds this section's type."""
        from dispatch.sections.registry import get_section_type
        return get_section_type(self.type)

    def parsed_params(self):
        """This section's params, validated against its type's own Params model."""
        section_module = self.section_type()
        try:
            return section_module.Params.model_validate(self.params)
        except Exception as error:
            raise ValueError(f'section "{self.id}" ({self.type}) has invalid params: {error}') from error


# ---------------------------------------------------------------- #
# The template
# ---------------------------------------------------------------- #

class Template(BaseModel):
    """A Dispatch Template, as written in `templates/<id>/template.json`."""

    model_config = ConfigDict(extra='forbid')

    id: str = Field(pattern=SLUG_PATTERN)
    schema_version: int
    name: str
    description: str
    subject: str
    layout_path: str
    required_properties: list[PropertyDefinition]
    globals: FilterSet = Field(default_factory=FilterSet)
    sections: list[SectionConfig]

    @field_validator('schema_version')
    @classmethod
    def check_schema_version(cls, version):
        """The job refuses a schema version it does not know."""
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            supported = ', '.join(str(number) for number in sorted(SUPPORTED_SCHEMA_VERSIONS))
            raise ValueError(f'schema_version {version} is not supported (supported: {supported})')
        return version

    @field_validator('subject')
    @classmethod
    def check_subject_placeholders(cls, subject):
        """A subject may only use the documented placeholders."""
        for placeholder in subject_placeholders(subject):
            if placeholder not in SUBJECT_PLACEHOLDERS:
                allowed = ', '.join(SUBJECT_PLACEHOLDERS)
                raise ValueError(f'unknown subject placeholder "{{{placeholder}}}". Allowed: {allowed}')
        return subject

    @model_validator(mode='after')
    def check_keys_are_unique(self):
        """Property keys and section ids must be unique, and required_when must name real values."""
        check_unique([definition.key for definition in self.required_properties], 'property key')
        check_unique([section.id for section in self.sections], 'section id')
        self.check_required_when()
        return self

    def check_required_when(self):
        """Each required_when must name another property and, for an enum, one of its options."""
        definitions_by_key = self.properties_by_key()
        for definition in self.required_properties:
            if not definition.required_when:
                continue
            for other_key, required_value in definition.required_when.items():
                other = definitions_by_key.get(other_key)
                if other is None:
                    raise ValueError(f'"{definition.key}" required_when names unknown property "{other_key}"')
                is_unknown_option = other.type == 'enum' and required_value not in other.options
                if is_unknown_option:
                    raise ValueError(
                        f'"{definition.key}" required_when expects "{other_key}" = {required_value!r}, '
                        f'which is not one of its options'
                    )

    def properties_by_key(self):
        """Return the property definitions as a map of key to definition."""
        definitions_by_key = {}
        for definition in self.required_properties:
            definitions_by_key[definition.key] = definition
        return definitions_by_key

    def validate_property_values(self, values):
        """
        Check a record's property values: presence, type, enum membership and required_when.

        Returns a cleaned copy holding every value supplied, so an optional state
        on a federal record is kept. Raises PropertyValuesError listing every problem found.
        """
        problems = []
        cleaned = {}
        definitions_by_key = self.properties_by_key()

        # A value for a property the template does not declare is a mistake in the record
        for key in values:
            if key not in definitions_by_key:
                problems.append(f'"{key}" is not a property of template "{self.id}"')

        # Check each declared property in order
        for definition in self.required_properties:
            value = values.get(definition.key)
            is_required = definition.is_required(values)

            # An absent property is a problem only when its condition holds
            if value is None:
                if is_required:
                    problems.append(f'"{definition.key}" is required')
                continue

            # A present value is checked and kept, required or not
            problem = definition.value_problem(value)
            if problem is not None:
                problems.append(problem)
                continue
            cleaned[definition.key] = value

        if problems:
            raise PropertyValuesError(problems)
        return cleaned

    def format_subject(self, placeholder_values):
        """Fill the subject's placeholders from a map of placeholder name to text."""
        return self.subject.format(**placeholder_values)


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

def subject_placeholders(subject):
    """Return the placeholder names a subject line uses, in order."""
    names = []
    for _literal, field_name, _format_spec, _conversion in string.Formatter().parse(subject):
        if field_name is None:
            continue
        names.append(field_name)
    return names


def check_unique(names, what):
    """Raise ValueError naming the first repeated name in a list."""
    seen = set()
    for name in names:
        if name in seen:
            raise ValueError(f'{what} "{name}" appears more than once')
        seen.add(name)
