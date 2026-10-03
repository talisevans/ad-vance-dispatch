"""
Reference data every section reads: bias definitions, affiliations, creators,
their colours, and the merges between affiliations.

The data is read once from the lookup cache views (`bias_definitions`,
`affiliations`, `content_creators`) that `data/gold.py` mounts. Colours follow
the dashboard exactly, so an email and the web app agree:

  1. An affiliation takes its stored `colour` when an admin has set one.
  2. Otherwise the deterministic fallback ported from
     `AdVance-front-end/src/app/shared/palette.ts`: a party colour, the
     independents' teal, or a categorical slot picked from a hash of the name.
  3. A bias takes its stored `bias_colour`, or one derived from its position.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------- #
# Colours for the unmapped and the rest
# ---------------------------------------------------------------- #

# The label and colour for spend whose creator has no bias
UNMAPPED_BIAS_LABEL = 'unmapped'
UNMAPPED_COLOUR = '#d1d5db'

# Where unmapped sits on the left to right axis
UNMAPPED_POSITION = 0.0

# The label for spend whose creator has no affiliation
UNMAPPED_AFFILIATION_LABEL = 'Unmapped'

# The bucket that gathers every affiliation outside a top N
OTHER_LABEL = 'Other'
OTHER_COLOUR = '#9ca3af'


def bias_display_name(label):
    """A bias label as people read it: "extreme left" becomes "Extreme left", unmapped becomes "Unmapped"."""
    if label is None or label == '':
        label = UNMAPPED_BIAS_LABEL
    return label[0].upper() + label[1:]


# ---------------------------------------------------------------- #
# The dashboard palette, ported from palette.ts
# ---------------------------------------------------------------- #

# The categorical order. The order is validated for colour-vision deficiency, so it is never shuffled
CATEGORICAL = (
    '#2563eb',  # blue 600
    '#f97316',  # orange 500
    '#0d9488',  # teal 600
    '#a21caf',  # fuchsia 700
    '#f59e0b',  # amber 500
    '#15803d',  # green 700
    '#f472b6',  # pink 400
    '#dc2626',  # red 600
)

# The teal every independent is drawn in
INDEPENDENT_TEAL = '#0d9488'

# Parties that campaign in a colour of their own, keyed on the canonical party name
PARTY_COLOURS = {
    'Labor': '#dc2626',                   # red 600
    'Liberal': '#1e3a8a',                 # blue 900
    'Greens': '#22c55e',                  # green 500
    'One Nation': '#f97316',              # orange 500
    'Liberal National Party': '#0369a1',  # sky 800
}

# The diverging scale a bias with no stored colour is placed on, by position
BIAS_POSITION_SCALE = (
    (-2.0, '#991b1b'),  # red 800, extreme left
    (-1.0, '#ef4444'),  # red 500, left
    (0.0, '#94a3b8'),   # slate 400, centrist
    (1.0, '#3b82f6'),   # blue 500, right
    (2.0, '#1e40af'),   # blue 800, extreme right
)

# The colour a position that is not a number takes
DERIVED_BIAS_FALLBACK = '#94a3b8'

# A 32-bit wrap, matching JavaScript's `| 0`
UINT32_MASK = 0xFFFFFFFF
INT32_LIMIT = 2 ** 31
UINT32_RANGE = 2 ** 32

# The multiplier in the dashboard's string hash
HASH_MULTIPLIER = 31


def reserved_colours():
    """Every colour that means one particular affiliation."""
    reserved = []
    for colour in PARTY_COLOURS.values():
        reserved.append(colour)
    reserved.append(INDEPENDENT_TEAL)
    return reserved


def affiliation_slots():
    """The categorical colours left for an affiliation that is neither a party nor an independent."""
    reserved = reserved_colours()
    slots = []
    for colour in CATEGORICAL:
        if colour in reserved:
            continue
        slots.append(colour)
    return slots


def wrap_to_int32(number):
    """Wrap an integer to a signed 32-bit value, as JavaScript's `| 0` does."""
    wrapped = number & UINT32_MASK
    if wrapped >= INT32_LIMIT:
        wrapped -= UINT32_RANGE
    return wrapped


def utf16_code_units(text):
    """The UTF-16 code units of a string, as JavaScript's `charCodeAt` reads them."""
    encoded = text.encode('utf-16-le')
    units = []
    for index in range(0, len(encoded), 2):
        unit = encoded[index] + (encoded[index + 1] << 8)
        units.append(unit)
    return units


def name_hash(text):
    """The dashboard's string hash: `hash = (hash * 31 + code) | 0` over each code unit."""
    hash_value = 0
    for code_unit in utf16_code_units(text):
        hash_value = wrap_to_int32(hash_value * HASH_MULTIPLIER + code_unit)
    return hash_value


def categorical_for(value, order=(), slots=CATEGORICAL):
    """A stable categorical colour: by position in a known order, else by a hash of the text."""
    if value in order:
        index = list(order).index(value)
        return slots[index % len(slots)]
    slot_index = abs(name_hash(value)) % len(slots)
    return slots[slot_index]


def is_independent(name):
    """Whether an affiliation name is an independent, of whatever lean."""
    if name == 'Independent':
        return True
    return name.startswith('Independent (')


def named_affiliation_colour(name):
    """The colour an affiliation owns by name (party or independent), or None when it has only a slot."""
    party_colour = PARTY_COLOURS.get(name)
    if party_colour:
        return party_colour
    if is_independent(name):
        return INDEPENDENT_TEAL
    return None


def fallback_affiliation_colour(name):
    """The dashboard's colour for an affiliation with no stored colour."""
    named_colour = named_affiliation_colour(name)
    if named_colour:
        return named_colour
    return categorical_for(name, (), affiliation_slots())


def parse_hex(colour):
    """Split a `#rrggbb` colour into its red, green and blue channels."""
    digits = colour.replace('#', '')
    red = int(digits[0:2], 16)
    green = int(digits[2:4], 16)
    blue = int(digits[4:6], 16)
    return red, green, blue


def round_half_up(number):
    """Round to the nearest integer with halves going up, as JavaScript's Math.round does."""
    return int(math.floor(number + 0.5))


def mix_colours(from_colour, to_colour, fraction):
    """Blend two hex colours in sRGB, `fraction` of the way from the first to the second."""
    start_channels = parse_hex(from_colour)
    end_channels = parse_hex(to_colour)

    # Blend each channel and write it back as two hex digits
    parts = []
    for start_channel, end_channel in zip(start_channels, end_channels):
        blended = round_half_up(start_channel + (end_channel - start_channel) * fraction)
        parts.append(f'{blended:02x}')
    return '#' + ''.join(parts)


def derived_bias_colour(position):
    """The colour a bias takes from its position alone, read off the diverging scale."""
    if position is None or math.isnan(position):
        return DERIVED_BIAS_FALLBACK

    first_position, first_colour = BIAS_POSITION_SCALE[0]
    last_position, last_colour = BIAS_POSITION_SCALE[-1]

    # Past either end of the scale, take the end colour
    if position <= first_position:
        return first_colour
    if position >= last_position:
        return last_colour

    # Blend the two stops the position sits between
    for index in range(len(BIAS_POSITION_SCALE) - 1):
        low_position, low_colour = BIAS_POSITION_SCALE[index]
        high_position, high_colour = BIAS_POSITION_SCALE[index + 1]
        is_between = low_position <= position <= high_position
        if not is_between:
            continue
        fraction = (position - low_position) / (high_position - low_position)
        return mix_colours(low_colour, high_colour, fraction)

    return DERIVED_BIAS_FALLBACK


# ---------------------------------------------------------------- #
# Records
# ---------------------------------------------------------------- #

@dataclass(frozen=True)
class BiasDefinition:
    """One defined bias: its name as gold holds it, its position and its colour."""
    bias_id: str
    name: str
    position: float
    colour: str


@dataclass(frozen=True)
class Affiliation:
    """One affiliation: its id, display name, bias, stored colour and merge pointer."""
    affiliation_id: str
    name: str
    bias: Optional[str]
    stored_colour: Optional[str]
    superseded_by: Optional[str]


@dataclass(frozen=True)
class Creator:
    """One content creator: its id, name, classification and affiliation."""
    creator_id: str
    name: str
    classification: Optional[str]
    affiliation_id: Optional[str]


@dataclass(frozen=True)
class BiasSlot:
    """One slot on the left to right axis: a defined bias, or unmapped (name None)."""
    label: str
    name: Optional[str]
    position: float
    colour: str


# ---------------------------------------------------------------- #
# Reading the lookup views
# ---------------------------------------------------------------- #

def has_text(value):
    """Whether a value is real, non-blank text."""
    if value is None:
        return False
    if not isinstance(value, str):
        return False
    return value.strip() != ''


def read_rows(connection, sql):
    """Run a query and return its rows as dictionaries."""
    cursor = connection.execute(sql)
    column_names = []
    for description in cursor.description:
        column_names.append(description[0])

    rows = []
    for values in cursor.fetchall():
        rows.append(dict(zip(column_names, values)))
    return rows


def read_bias_definitions(connection):
    """Read every bias definition, ordered by position then name."""
    rows = read_rows(
        connection,
        'SELECT bias_id, bias_name, bias_position, bias_colour FROM bias_definitions',
    )

    definitions = []
    for row in rows:
        position = float(row['bias_position'])

        # A stored colour wins; otherwise the colour comes from the position
        colour = derived_bias_colour(position)
        if has_text(row['bias_colour']):
            colour = row['bias_colour'].lower()

        definitions.append(BiasDefinition(
            bias_id=row['bias_id'],
            name=row['bias_name'],
            position=position,
            colour=colour,
        ))

    definitions.sort(key=lambda definition: (definition.position, definition.name))
    return definitions


def read_affiliations(connection):
    """Read every affiliation, keyed by id."""
    rows = read_rows(
        connection,
        'SELECT affiliation_id, affiliation_name, affiliation_bias, colour, '
        'affiliation_superseded_by FROM affiliations',
    )

    affiliations = {}
    for row in rows:
        # A blank colour or pointer means none was set
        stored_colour = None
        if has_text(row['colour']):
            stored_colour = row['colour'].lower()
        superseded_by = None
        if has_text(row['affiliation_superseded_by']):
            superseded_by = row['affiliation_superseded_by']

        affiliations[row['affiliation_id']] = Affiliation(
            affiliation_id=row['affiliation_id'],
            name=row['affiliation_name'],
            bias=row['affiliation_bias'],
            stored_colour=stored_colour,
            superseded_by=superseded_by,
        )
    return affiliations


def read_creators(connection):
    """Read every content creator, keyed by id."""
    rows = read_rows(
        connection,
        'SELECT creator_id, creator_name, creator_classification, creator_affiliation_id '
        'FROM content_creators',
    )

    creators = {}
    for row in rows:
        creators[row['creator_id']] = Creator(
            creator_id=row['creator_id'],
            name=row['creator_name'],
            classification=row['creator_classification'],
            affiliation_id=row['creator_affiliation_id'],
        )
    return creators


# ---------------------------------------------------------------- #
# The reference data
# ---------------------------------------------------------------- #

@dataclass
class ReferenceData:
    """Biases, affiliations and creators, with the colour and merge rules over them."""
    biases: list = field(default_factory=list)
    affiliations: dict = field(default_factory=dict)
    creators: dict = field(default_factory=dict)

    # Seat margins by unique electorate id, or None while no seat lookup is published
    seat_margins: Optional[dict] = None

    @classmethod
    def load(cls, connection):
        """Read the three lookup views from an open gold connection."""
        return cls(
            biases=read_bias_definitions(connection),
            affiliations=read_affiliations(connection),
            creators=read_creators(connection),
        )

    # ------------------------------------------------------------ #
    # Affiliation merges
    # ------------------------------------------------------------ #

    def resolve_affiliation_id(self, affiliation_id):
        """The id that finally survives a chain of merges. Unknown and None ids answer as themselves."""
        if affiliation_id is None:
            return None

        current_id = affiliation_id
        visited_ids = [current_id]

        # Step along the merge pointers until one is empty, missing or loops
        while True:
            affiliation = self.affiliations.get(current_id)
            if affiliation is None:
                return current_id

            target_id = affiliation.superseded_by
            if target_id is None:
                return current_id
            if target_id in visited_ids:
                return current_id
            if target_id not in self.affiliations:
                return current_id

            visited_ids.append(target_id)
            current_id = target_id

    def affiliation_group(self, affiliation_id):
        """Every id in an affiliation's merge group: the survivor first, then each id merged into it."""
        survivor_id = self.resolve_affiliation_id(affiliation_id)
        group = [survivor_id]

        # Add every other id whose chain ends at the same survivor
        for other_id in sorted(self.affiliations):
            if other_id == survivor_id:
                continue
            other_survivor = self.resolve_affiliation_id(other_id)
            if other_survivor == survivor_id:
                group.append(other_id)

        # The id asked about is always in its own group
        if affiliation_id not in group:
            group.append(affiliation_id)
        return group

    # ------------------------------------------------------------ #
    # Affiliation names and colours
    # ------------------------------------------------------------ #

    def affiliation_name(self, affiliation_id):
        """The display name of an affiliation after merges, or the id itself when unknown."""
        survivor_id = self.resolve_affiliation_id(affiliation_id)
        affiliation = self.affiliations.get(survivor_id)
        if affiliation is None:
            return survivor_id
        return affiliation.name

    def affiliation_colour(self, affiliation_id):
        """The colour an affiliation is drawn in: stored, else the dashboard's fallback by name."""
        if affiliation_id is None:
            return UNMAPPED_COLOUR

        survivor_id = self.resolve_affiliation_id(affiliation_id)
        affiliation = self.affiliations.get(survivor_id)

        # An affiliation the cache does not hold is coloured from its id
        if affiliation is None:
            return fallback_affiliation_colour(survivor_id)

        if affiliation.stored_colour:
            return affiliation.stored_colour
        return fallback_affiliation_colour(affiliation.name)

    # ------------------------------------------------------------ #
    # Creators
    # ------------------------------------------------------------ #

    def creator_name(self, creator_id, fallback=None):
        """A creator's name from the cache, or the fallback (then the id) when the cache lacks it."""
        creator = self.creators.get(creator_id)
        if creator is not None and has_text(creator.name):
            return creator.name
        if fallback is not None:
            return fallback
        return creator_id

    # ------------------------------------------------------------ #
    # Seats
    # ------------------------------------------------------------ #

    def seat_margin_lookup(self):
        """
        Margin text by unique electorate id, or None when no seat lookup exists.

        The seat lookup (members and margins) is a separate back-end project and is
        not published yet, so `load` leaves `seat_margins` empty and this answers
        None. Top Seats hides its Margin column whenever this is None (D21).
        """
        if not self.seat_margins:
            return None
        return self.seat_margins

    # ------------------------------------------------------------ #
    # Biases
    # ------------------------------------------------------------ #

    def bias_definition(self, bias_name):
        """The definition for a bias name, or None when it is not defined."""
        for definition in self.biases:
            if definition.name == bias_name:
                return definition
        return None

    def bias_colour(self, bias_name):
        """The colour for a bias name. Null and unmapped take the neutral grey."""
        if bias_name is None or bias_name == UNMAPPED_BIAS_LABEL:
            return UNMAPPED_COLOUR
        definition = self.bias_definition(bias_name)
        if definition is None:
            return UNMAPPED_COLOUR
        return definition.colour

    def bias_position(self, bias_name):
        """The position for a bias name. Null and unmapped sit at zero."""
        if bias_name is None or bias_name == UNMAPPED_BIAS_LABEL:
            return UNMAPPED_POSITION
        definition = self.bias_definition(bias_name)
        if definition is None:
            return UNMAPPED_POSITION
        return definition.position

    def bias_slots(self):
        """Every bias left to right, with unmapped straight after the last bias at or below zero."""
        slots = []
        unmapped_placed = False

        unmapped_slot = BiasSlot(
            label=UNMAPPED_BIAS_LABEL,
            name=None,
            position=UNMAPPED_POSITION,
            colour=UNMAPPED_COLOUR,
        )

        # Walk the definitions in position order, slotting unmapped in once the positions pass zero
        for definition in self.biases:
            is_past_zero = definition.position > UNMAPPED_POSITION
            if is_past_zero and not unmapped_placed:
                slots.append(unmapped_slot)
                unmapped_placed = True
            slots.append(BiasSlot(
                label=definition.name,
                name=definition.name,
                position=definition.position,
                colour=definition.colour,
            ))

        # Every bias sat at or below zero, so unmapped goes last
        if not unmapped_placed:
            slots.append(unmapped_slot)
        return slots
