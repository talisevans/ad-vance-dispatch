# Dispatch contracts

What a section author, chart author or template author can rely on. Everything here is in
`src/dispatch/`; the plan (`plan/2026-10-03_implementation_plan.md`) is the design.

## 1. The section module contract (`sections/base.py`)

A section type is one folder `src/dispatch/sections/<type>/` holding the module
`<type>.py`, its partial `<type>.html.j2` and an `__init__.py`. The module exposes:

| Name | Type | Meaning |
|---|---|---|
| `TYPE_NAME` | `str` | The name templates use, e.g. `"bias_gauge"`. |
| `Params` | pydantic `BaseModel` | The section's params. Use `model_config = ConfigDict(extra='forbid')` so a typo in a template fails at publish time. Give every field a default from the plan. |
| `DESCRIPTION` | `str` | What the section is for (catalogue). |
| `RENDERS` | `str` | One line on what it draws (catalogue). |
| `PARTIAL` | `str` | The partial's file name, e.g. `"bias_gauge.html.j2"`. |
| `build(context, params)` | function | Returns a `SectionResult`. `params` is an instance of `Params`. |

`build` must not send, upload or write anything. If it raises, the whole run fails (plan 5.2 step 6).

### SectionResult

```python
@dataclass
class SectionResult:
    variables: dict          # what the partial reads as section.variables
    images: list             # ChartImage objects
    notes: list              # footnote strings, read as section.notes
    summary_lines: list      # plain-text lines for the text/plain part (headline figures)
```

### ChartImage

```python
@dataclass
class ChartImage:
    name: str                # unique within the section, e.g. "gauge"; partial reads section.images.<name>
    png: bytes
    display_width: int       # CSS pixels, e.g. 290 or 580
    display_height: int
    alt: str                 # states the key figures, for clients that block images
```

The Content-ID is `<section id>-<name>`, for example `statewide_spend-gauge`. Archive file:
`sent/<record>/<slot>/<section id>-<name>.png`.

## 2. SectionContext

`build_section` in `build.py` creates one context per section. Fields:

| Field | Type | Meaning |
|---|---|---|
| `connection` | DuckDB connection | Every gold table, apportioned view and lookup view mounted (section 6). |
| `record` | `DispatchRecord` | The record being sent. |
| `template` | `Template` | Its template. |
| `section` | `SectionConfig` | This section's `id`, `type`, `params`, `include`, `exclude`. |
| `property_values` | `dict` | The record's validated property values. |
| `jurisdiction` | `str` | `"federal"` or `"state"`. Hard filter (ADR 0001). |
| `state` | `str` or `None` | State code (`"VIC"`), or `None` for a national federal record. |
| `dates` | `DataDates` | as_of, record range, Google's latest day (section 3). |
| `reference` | `ReferenceData` | Biases, affiliations, creators, colours, merges (section 4). |
| `filter_sql` | `str` | Template globals AND this section's include/exclude, compiled. Reads columns as `adverts.<column>`. `TRUE` when there is no filter. |
| `filter_parameters` | `dict` | Named parameters `filter_0`, `filter_1`, ... bound by `filter_sql`. |

Convenience members:

| Member | Returns |
|---|---|
| `as_of`, `start_date`, `end_date`, `window_end` | `datetime.date` |
| `window(days)` | `DateWindow(days, start, end)` with `.sentence`, e.g. "Figures reflect the 7-day window 25 September to 1 October 2026". Inclusive both ends, ending at `window_end`. |
| `query(sql, parameters=None)` | `list[dict]`. Binds `filter_parameters`, `$jurisdiction`, `$state` and your extra parameters, passing only the names the SQL mentions (DuckDB refuses unused ones). A `$name` nobody supplies raises `KeyError`. |
| `statewide_spend_sql()` | A subquery string of apportioned spend rows for the record's scope, filter applied. |
| `seat_spend_sql()` | A subquery string of apportioned spend rows per seat in scope, filter applied. |
| `scope_parameters()`, `all_parameters(extra)` | The parameter dictionaries `query` uses. |

### The scope subqueries

Both already apply the hard jurisdiction filter and `filter_sql`. Wrap them and add your own date
window and grouping:

```python
window = context.window(params.window_days)
rows = context.query(
    f"SELECT coalesce(creator_affiliation_bias, 'unmapped') AS bias, sum(spend) AS spend "
    f"FROM ({context.statewide_spend_sql()}) AS scoped "
    f"WHERE scoped.date BETWEEN $window_start AND $window_end "
    f"  AND scoped.creator_classification IS DISTINCT FROM 'government' "
    f"GROUP BY 1",
    {'window_start': window.start, 'window_end': window.end},
)
```

`statewide_spend_sql()` columns: `ad_key, date, spend`, then the advert columns `datasource,
approach, themes, creator_id, creator_name, creator_classification, creator_affiliation_id,
creator_affiliation, creator_affiliation_bias, is_local_government_content`.

- State record, or federal record with a state: reads `ad_state_daily` where `state = $state`.
- Federal record with no state: reads national `ad_daily` (`spend_avg AS spend`).

`seat_spend_sql()` columns: `ad_key, date, spend, unique_electorate_id, electorate_name,
electorate_state`, then the same advert columns. It reads `ad_geo_daily` joined to `electorates`,
keeping seats whose `electorates.jurisdiction` is the record's, narrowed to `$state` when set.

Rules that stay the section's job:

- Never sum themes across an advert into a total (ADR 0003). `unnest(themes)` per theme only.
- Government is always dropped from bias views (D17), on top of the template's filters. The
  constant `sections.base.GOVERNMENT_CLASSIFICATION` is `"government"`.
- Name your own parameters without the `filter_` prefix, and not `jurisdiction` or `state`.
- Use the window from `context.window(...)`, never the run date.

## 3. Dates (`data/as_of.py`)

`DataDates` fields: `as_of` (latest Meta `ad_daily.date` in all of gold), `start_date` and
`end_date` (record properties), `google_latest`. Properties: `window_end` (earlier of `as_of` and
`end_date`), `window(days)`, `google_incomplete`, `google_callout` (text or `None`). The skeleton
already shows the Google callout; sections do not.

## 4. Reference data (`data/reference.py`)

`ReferenceData` is read once per run from the lookup views.

| Member | Meaning |
|---|---|
| `biases` | `BiasDefinition(bias_id, name, position, colour)` list, ordered by position then name. Colour is stored `bias_colour` or derived from position. |
| `bias_slots()` | `BiasSlot(label, name, position, colour)` left to right with `unmapped` (name `None`, position 0, `#d1d5db`) straight after the last bias at or below 0, i.e. after `centrist`. |
| `bias_colour(name)`, `bias_position(name)` | `None` or `"unmapped"` give `#d1d5db` and `0.0`. |
| `affiliations` | `dict` id to `Affiliation(affiliation_id, name, bias, stored_colour, superseded_by)`. |
| `resolve_affiliation_id(id)` | The id that survives a chain of merges. Unknown ids answer as themselves. |
| `affiliation_group(id)` | Survivor first, then every id merged into it. Filters use this. |
| `affiliation_name(id)` | Name after merges. |
| `affiliation_colour(id)` | Stored colour, else the dashboard fallback (party colour, independent teal, hash slot), exactly as `palette.ts`. `None` gives `#d1d5db`. |
| `creators` | `dict` id to `Creator(creator_id, name, classification, affiliation_id)`. |
| `creator_name(id, fallback=None)` | Cache name, else the fallback, else the id. |
| `seat_margin_lookup()` | Margin text by unique electorate id, or `None` when no seat lookup exists. The lookup is a parked back-end project, so `load` leaves `seat_margins` as `None` and this answers `None` today. Top Seats hides its Margin column on `None` (D21). |

Functions: `bias_display_name(label)` ("extreme left" to "Extreme left", `None` to "Unmapped"), `round_half_up(number)`.

Constants: `UNMAPPED_BIAS_LABEL = "unmapped"`, `UNMAPPED_COLOUR = "#d1d5db"`,
`UNMAPPED_AFFILIATION_LABEL = "Unmapped"`, `OTHER_LABEL = "Other"`, `OTHER_COLOUR = "#9ca3af"`.

Gold may still carry a merged id (the fixtures do: `aff_lib_old`). Group by
`resolve_affiliation_id(...)` in Python when a section reports per affiliation.

## 5. Filters (`filters/`)

Template `include` and `exclude` maps compile into `filter_sql`. Values are OR'd within a key, keys
AND'd, and the section's sets AND'd onto the globals, so a section can only narrow. `null` means
unmapped (for `theme`, an advert with no themes). `affiliation_id` values widen to their merge group.

| Key | Kind | Column | v1 |
|---|---|---|---|
| `classification` | select | `adverts.creator_classification` | yes |
| `affiliation_id` | select | `adverts.creator_affiliation_id` | yes |
| `bias` | select | `adverts.creator_affiliation_bias` | yes |
| `creator_id` | select | `adverts.creator_id` | yes |
| `datasource` | select | `adverts.datasource` | yes |
| `approach` | select | `adverts.approach` | yes |
| `theme` | select | `adverts.themes` (any match) | yes |
| `is_local_government_content` | select | `adverts.is_local_government_content` (true/false values) | yes |
| `age_range`, `gender`, `platform`, `electorate_id` | weight | `ad_demo`, `ad_platform`, `ad_geo` | registered, refused |

## 6. Gold in DuckDB (`data/gold.py`)

Views on the connection: `ad_daily, adverts, ad_geo, ad_state, ad_demo, ad_platform, electorates`
(with `year` from the hive path), the apportioned `ad_geo_daily, ad_state_daily, ad_demo_daily,
ad_platform_daily` (columns `ad_key, date, jurisdiction, year, <buckets>, weight, spend,
impressions`, copied from `AdVance-api/lib/duck.ts`), and the lookups `affiliations,
bias_definitions, content_creators` (newest row per key, `_cache_written_at` and `*_manual_classified_by`
hidden).

Where the parquet comes from: `resolve_gold_source(gold_directory=None, lookups_directory=None)`.
An argument wins, then `DISPATCH_GOLD_DIR` / `DISPATCH_LOOKUPS_DIR`, then a download from
`gs://advance_gold` and `gs://advance_lookups/caches/`. Lookups default to `<gold>/lookups`. Open
with `open_gold_from(source)`.

## 7. Registering a section

`sections/registry.py` holds one explicit dictionary. The four v1 types are registered:

```python
from dispatch.sections.bias_gauge import bias_gauge
from dispatch.sections.cumulative_spend import cumulative_spend
from dispatch.sections.messaging_tone import messaging_tone
from dispatch.sections.top_seats import top_seats

SECTION_TYPES = {
    bias_gauge.TYPE_NAME: bias_gauge,
    cumulative_spend.TYPE_NAME: cumulative_spend,
    messaging_tone.TYPE_NAME: messaging_tone,
    top_seats.TYPE_NAME: top_seats,
}
```

`Template` validation looks types up here, so a template naming an unregistered type, or params
its `Params` refuses, fails at publish time. Tests may add a type for one test and remove it
(see the `registered_probe` fixture in `tests/conftest.py`).

## 8. Partials and layouts (`render/`)

The Jinja2 environment searches, in order: the layout (registered as `layout.html.j2`), each built
section's own folder (`src/dispatch/sections/<type>/`), `src/dispatch/sections/`, then `src/dispatch/render/` (the
skeleton). Autoescape is on and undefined variables raise (`StrictUndefined`).

A layout:

```jinja
{% extends "email_skeleton.html.j2" %}
{% block header %} ...one or more <tr> rows... {% endblock %}
```

The skeleton provides the `<!--[if mso]>` 640px table, the "Not displaying properly? View it in your
browser." row (email render only), the `[TEST]` banner, the Google callout, the `sections` block
(which includes each partial in order) and the footer (data source, window sentence, unsubscribe
contact). Blocks a layout may override: `extra_styles`, `preheader`, `header`, `sections`, `footer`.

A partial renders **one or more `<tr>` rows** of the 640px container table: tables with
`role="presentation"`, inline styles (classes in the skeleton's `<style>` are inlined by premailer),
`bgcolor` beside CSS backgrounds, cell padding not margins, no SVG, flexbox or grid. Two-column
layouts use `class="stack-column"` cells, which stack on clients that honour media queries; images
in them use `class="stack-image"`.

Inside a partial:

| Name | Meaning |
|---|---|
| `section.id`, `section.type`, `section.partial` | This section. |
| `section.variables` | `SectionResult.variables`. |
| `section.images.<name>` | `.src` (`cid:...` in email, `data:image/png;base64,...` in the browser copy), `.width`, `.height`, `.alt`, `.content_id`. |
| `section.notes` | Footnotes. |
| `dispatch.*` | `mode` (`email`/`browser`), `subject`, `is_test`, `template_name`, `record_name`, `jurisdiction`, `state`, `jurisdiction_label`, `as_of`, `as_of_long`, `start_date`, `end_date`, `window_end`, `window_start` (7-day), `window_range` (7-day, e.g. "25 September to 1 October 2026"), `window_sentence` (7-day), `data_source_sentence`, `callouts`, `contact_email`, `browser_url`, `property_values`. |

Filters: `money` ("$4,487"), `money_short` ("$1.2m", "$45k"), `percent` (0.42 to "42%"),
`long_date` ("1 October 2026"), `day_month` ("25 September"), `short_date` ("25 Sep"). The same
functions are in `dispatch.formatting` for Python, with `safe_share(part, whole)`,
`format_date_range`, `window_sentence` and `jurisdiction_label`.

Example image tag:

```jinja
<img src="{{ section.images.gauge.src }}" width="{{ section.images.gauge.width }}"
     height="{{ section.images.gauge.height }}" alt="{{ section.images.gauge.alt }}"
     style="display: block; border: 0;" />
```

## 9. Chart helpers (`charts/style.py`)

Importing it selects matplotlib's Agg backend and sets fonts (Arial, Liberation Sans, DejaVu Sans)
and chrome colours.

| Name | Meaning |
|---|---|
| `new_figure(display_width, display_height)` | `(figure, axes)` sized in display pixels. |
| `style_axes(axes)` | No top/right spines, light horizontal gridlines under the data, no ticks. |
| `money_axis(axes)` | y tick labels in short money. |
| `chart_image(name, figure, display_width, display_height, alt)` | Saves at 2x on opaque white, closes the figure, returns a `ChartImage`. |
| `figure_to_png(figure)` | The PNG bytes alone. |
| `DENSITY` (2), `BASE_DPI` (100), `SAVE_DPI` (200) | A 290px chart is a 580px PNG. |
| `FULL_CHART_WIDTH` (580), `HALF_CHART_WIDTH` (290), `EMAIL_WIDTH` (640) | Display widths. |
| `TITLE_FONT_SIZE`, `LABEL_FONT_SIZE`, `TICK_FONT_SIZE`, `SMALL_FONT_SIZE` | Points at display size. |
| `NAVY`, `SURFACE`, `INK`, `INK_SECONDARY`, `INK_MUTED`, `GRIDLINE`, `AXIS` | Colours. |
| `SERIES_LINE_WIDTH`, `GRID_LINE_WIDTH` | Line widths in points. |

Do not use `bbox_inches='tight'`; it changes the pixel size away from 2x the display size.

### Chart modules

| Module | Function | Draws |
|---|---|---|
| `charts/gauge.py` | `half_doughnut_chart(name, segments, total, caption, alt)` | `GaugeSegment(label, value, colour)` list, left to right, as a half ring 400 x 210 display pixels, total and caption in the middle. No spend draws an empty grey ring. |
| `charts/lines.py` | `cumulative_line_chart(name, dates, series_list, alt, display_width=290)` | `LineSeries(label, colour, values)` list, one value per date, 200 display pixels tall, at most four date labels, a dot on each line's end, no end labels. No spend draws "No spend in this period". |

## 10. Templates (`models/template.py`)

`Template` fields: `id` (slug), `schema_version` (must be in `SUPPORTED_SCHEMA_VERSIONS = {1}`),
`name`, `description`, `subject`, `layout_path` (`templates/emails/<id>/layout.html.j2`),
`required_properties`, `globals` (`FilterSet`), `sections` (`SectionConfig` list).

Property types: `date` (`YYYY-MM-DD`), `enum` (needs `options`), `string`, `number`,
`affiliation_list`. `required_when` maps another key to the value that makes this one required.
`Template.validate_property_values(values)` returns every supplied value once checked (an optional
`state` on a federal record is kept, as a narrowing to one state) and raises
`PropertyValuesError` listing every problem. Every Dispatch needs `jurisdiction`, `start_date`
and `end_date` properties; `state` is used when present.

Subject placeholders: `{jurisdiction_label}`, `{as_of_long}`, `{window_start_long}` (7-day window
start), `{template_name}`, `{record_name}`.

`publish-templates` runs inside the deployed image only (README, "Publishing"); `--dry-run` runs
anywhere. It renders each template against the fixtures once per branch of its
`required_when` conditions (for the Weekly Campaign Brief: federal, then state with `NSW`), using
`start_date 2026-08-01` and `end_date 2026-11-28`. The catalogue stores JSON Schemas as JSON
strings (`template_json_schema`, `params_json_schema`), because Firestore cannot hold nested arrays.

Samples (`render/samples.py`): each section type is built once over the fixtures for VIC state
seats, using the settings of its first use in a template (or its default params), and rendered alone
in `render/sample_frame.html.j2`. Each email template's sample is its first property set rendered in
its layout. Samples keep CSS in a `<style>` block, replace every `<img>` with a box quoting the
chart's size and alt text, and open with the made-up data notice. Both the skeleton and the sample
frame include `render/email_styles.css.j2`, so samples look like the email.

## 10a. The v1 section types

| Type | Params (defaults) | Images | Variables the partial reads |
|---|---|---|---|
| `bias_gauge` | `window_days` (7) | `gauge` | `heading`, `window_days`, `window_sentence`, `headlines` (label, amount, colour, align), `total`, `legend` (label, name, colour, amount, share) |
| `cumulative_spend` | `interval` (`week` only), `top_affiliations` (8) | `biases`, `affiliations` | `heading`, `columns` (title, image_name, rows of name, colour, total), `grand_total`, `period_text` |
| `messaging_tone` | `window_days` (28), `top_themes` (5), `cards` (label, affiliation_ids, optional colour) | none | `heading`, `window_days`, `window_sentence`, `cards`, `card_rows` (cards in pairs) |
| `top_seats` | `limit` (10), `windows` ([7, 28]), `rank_by_window` (7, must be in `windows`) | none | `heading`, `show_margin`, `window_columns`, `rows` (rank, seat, margin, leader, runner_up, bar_colour, totals), `no_runner_up`, `unmapped_tag`, `window_sentence` |

Rules each type keeps:

- `bias_gauge` and `cumulative_spend` drop government themselves (`IS DISTINCT FROM 'government'`),
  on top of the template's filters, and say so in a note.
- `cumulative_spend` points are the last day of each Monday-to-Sunday week, the final one cut at
  the window end. Affiliations fold merges into their survivor. Tables are highest first, Other
  and Unmapped included.
- `messaging_tone` cards match each listed id's whole merge group. Tones: positive, neutral,
  compare and contrast, negative, any other value gold holds, then Unclassified (null). Tone
  widths are whole percentages summing to 100. Themes count in full per advert.
- `top_seats` keys spenders by surviving `affiliation_id`, or `creator:<creator_id>` when
  unmapped. Seats with no spend in the ranking window are left out. Seat ties break on name,
  spender ties on key.
- Bar widths round halves up (62.5% draws as 63%).

## 11. Fixtures

`tests/fixtures/README.md` lists every fixture advert and the hand-checkable totals: bias splits,
cumulative by affiliation and by week, messaging tone and themes, Top Seats spenders with the
Brunswick leader tie and the two unmapped Kew independents, NSW and federal totals. Those numbers
are asserted in `tests/test_fixture_totals.py`. Pytest fixtures: `gold_connection`, `reference`,
`registered_probe`, `make_services` (whole runs with fake Firestore, layouts, archive, mailer and
Scheduler).

## 12. Fakes for outside services

| Seam | Real | Fake |
|---|---|---|
| Firestore | `store.firestore.FirestoreDispatchStore` | `FakeDispatchStore` |
| Layouts | `render.layout.GcsLayoutStore` | `LocalLayoutStore(root)` |
| Gold | `data.gold.GcsGoldSource` | `LocalGoldSource(gold, lookups)` |
| Archive and signing | `delivery.archive.GcsArchiveStore` | `FakeArchiveStore` |
| SES | `delivery.ses.SmtpMailer` | `FakeMailer(failing_recipients)` |
| Scheduler | `scheduling.scheduler.CloudSchedulerClient` | `FakeSchedulerClient(existing)` |
