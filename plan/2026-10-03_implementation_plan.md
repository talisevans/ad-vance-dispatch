# Dispatch: implementation plan

Date: 2026-10-03
Status: **Planned.** Nothing built yet.
Brief: `../prompt.md`. Starting design: `../vic_election_weekly_briefing.html`.
Repos: Dispatch job (`AdVance-dispatch`, new), API and MCP (`AdVance-api`), front end (`AdVance-front-end`).
Related, parked: seat members and margins lookup (separate back-end plan, see section 13).

## 1. Goal

Let admins schedule recurring HTML email briefings, built from gold data, to a list of recipients.

- A **Dispatch Template** is written by a developer. It says what the email contains, which
  properties a user must supply, and how each section filters the data.
- A **Dispatch Record** is created by an admin in the web app. It picks a template, fills in its
  properties, and sets recipients, schedule and delivery window.
- A **Dispatch** is one email, built by a Cloud Run job when a record's schedule fires.

The first template is the Weekly Campaign Brief, rebuilt from `vic_election_weekly_briefing.html`.

## 2. Decisions

Settled in the design review on 2026-10-03. Each one is binding on the phases below.

| # | Decision |
|---|----------|
| D1 | Charts are rendered to PNG on the server and attached inline (CID). The email targets legacy Outlook (Word rendering engine) as well as modern clients: table layout, inline CSS, no SVG, no flexbox or grid, 640px maximum width. |
| D2 | The Dispatch job is Python 3.11 in `AdVance-dispatch`, with its own Docker image and its own Cloud Run job. DuckDB reads gold parquet, Jinja2 renders, matplotlib draws charts, SES sends over SMTP. |
| D3 | One Cloud Scheduler trigger per Dispatch Record, named `dispatch-<record_id>`. The API creates, updates, pauses and deletes it when the record is saved. The trigger runs the job with `--record-id <id>`. Firestore is the source of truth; re-saving a record repairs any drift. |
| D4 | The UI offers schedule presets (daily, or weekly on chosen days, at a chosen time), never free cron. The preset is stored and the cron string is derived from it on save. |
| D5 | The job checks `status`, `start_delivery` and `end_delivery` itself, because Scheduler has no date range. On its first run after `end_delivery` it deletes its own trigger and exits cleanly. |
| D6 | `required_properties` is an ordered list of property definitions (`key`, `label`, `type`, `options`, `required_when`). The record holds a plain `property_values` object. Jurisdiction options are `federal` and `state` only. |
| D7 | `start_date` and `end_date` in property values are the data range. The data window ends at the earlier of `end_date` and `as_of` (D16). `start_date` anchors cumulative charts. |
| D8 | Filters use `include` and `exclude` maps of key to value list. Values are OR within a key, AND across keys. Section rules stack on global rules and can only narrow. `null` in a list means unmapped. Keys are ids, never display names. |
| D9 | A filter registry declares every key with its source and kind. `select` keys keep or drop whole adverts. `weight` keys (age, gender, platform, electorate) multiply spend by a share, as ADR 0006 requires. v1 implements the `select` keys; `weight` keys are a registered extension point. Unknown keys fail validation. |
| D10 | Sections are an ordered list. Each item has an `id`, a reusable `type`, `params`, and optional `include` and `exclude`. Each type is one Python module with a pydantic params model and its own Jinja2 partial. |
| D11 | The repo is the source of truth for templates. `publish-templates` validates them, uploads layouts to `gs://advance_dispatch/templates/<id>/`, and upserts `dispatch_templates/<id>` in Firestore. Section partials ship inside the image. Templates carry a `schema_version`; the job refuses one it does not know. Template ids are readable slugs. |
| D12 | Dispatch Records live in the default Firestore database. Shape in section 3.2. "Expired" is derived from `end_delivery`, never stored. |
| D13 | Recipients may be any address, at most 50 per record. One email per recipient. |
| D14 | The footer says to email the record's contact to unsubscribe. The contact defaults to `created_by` and can be overridden. `Reply-To` is set to the contact. |
| D15 | If some sends fail, the rest still go. The run is marked `partial`, and the job exits non-zero so the Cloud Run failure alert fires. |
| D16 | `as_of` is the latest `ad_daily.date` for Meta adverts across the whole gold table. Every window counts back from it. The email quotes the window, for example "Figures reflect the 7-day window 25 September to 1 October 2026". If Google has no rows up to `as_of`, the email carries a "Google data incomplete" callout. |
| D17 | The bias gauge orders biases by `bias_position` and colours them with `bias_colour`. Unmapped (null bias) sits at position 0, straight after `centrist`, in a neutral grey. Headline totals are Left (position below 0), Centre and unmapped (0), Right (above 0). Government classification is always dropped from bias views, with a note saying so. |
| D18 | Cumulative spend has two columns: biases on the left, the top N affiliations plus Other and Unmapped on the right. Each chart is its own PNG at 2x density, displayed 290px wide, with a value table under it in place of line-end labels. |
| D19 | Messaging cards are defined in `params.cards`, each with a `label` and `affiliation_ids`. Cards are ordered by spend. A card with no spend is kept and greyed. Null tone shows as an Unclassified slice. Tone and theme bars are table cells, not images. |
| D20 | In Top Seats, the spender key is `affiliation_id`. Unmapped creators group by `creator_id` and show their creator name with an "unmapped" tag. Seats rank by 7-day apportioned spend; leader and runner-up rank by 7-day spend within the seat; ties break on spender id. |
| D21 | Seat margins come from a separate, parked back-end project. Top Seats shows the Margin column only when that lookup exists for the jurisdiction. |
| D22 | The side pane has "Send test to me" (only the signed-in admin, `[TEST]` subject, no ledger) and "Send now" (full list, behind a confirm, fresh slot). Both run the real job. No in-browser preview. |
| D23 | A per-slot, per-recipient ledger in `dispatch_records/<id>/runs/<slot>` makes reruns safe: a rerun sends only to recipients not yet marked `sent`. |
| D24 | Each run's rendered HTML and charts are archived to `gs://advance_dispatch/sent/<record_id>/<slot>/`. Archive objects and ledger documents expire after 30 days. |
| D25 | Delete is a hard delete of record, ledger and trigger. Expired records stay editable; moving `end_delivery` forward revives them. Records can be duplicated. Paused records show on the Active tab with a badge. |
| D26 | Outlook compatibility comes from a proven skeleton (outer 640px table wrapped in an `<!--[if mso]>` conditional table, CSS inlined at render time). No paid rendering service. Manual test sends to Gmail, Apple Mail and Outlook.com. |
| D27 | Every email opens with "Not displaying properly? View it in your browser." The link is a V4 signed URL (7-day maximum) to `browser.html` in the archive, a second render with chart PNGs embedded as base64. |
| D28 | Three new MCP tools: `dispatch_template_guide`, `list_dispatch_records` and `list_dispatch_sections`. They read generated catalogue documents in Firestore. `list_dispatch_records` redacts recipient addresses and admin emails. |

Defaults taken without a separate decision:

- Admin CRUD goes through new `/api/admin/dispatch/*` routes. The front end never reads Firestore.
- The subject line is a template field with placeholders.
- Sender is `AdVance Dispatch <no-reply@talisevans.dev>` over the existing `aws_ses` secret.
- Dispatch is not registered in `runtime_jobs`, because it has no fixed frequency. Failures surface
  through the existing Cloud Run failure alert policy and through `last_run`.
- The bucket `gs://advance_dispatch` already exists in `advance-campaign-app`.

## 3. Data model

### 3.1 Dispatch Template (`dispatch_templates/<template_id>`, default database)

Written only by `publish-templates`. Source file: `templates/<template_id>/template.json`.

```json
{
  "id": "weekly_campaign_brief",
  "schema_version": 1,
  "name": "Weekly Campaign Brief",
  "description": "Weekly ad spend briefing for one jurisdiction: bias gauge, cumulative spend, messaging and top seats.",
  "subject": "{jurisdiction_label} election brief, week to {as_of_long}",
  "layout_path": "templates/weekly_campaign_brief/layout.html.j2",
  "required_properties": [
    { "key": "start_date",   "label": "Data from",    "type": "date" },
    { "key": "end_date",     "label": "Data to",      "type": "date" },
    { "key": "jurisdiction", "label": "Jurisdiction", "type": "enum",
      "options": ["federal", "state"] },
    { "key": "state",        "label": "State",        "type": "enum",
      "options": ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"],
      "required_when": { "jurisdiction": "state" } }
  ],
  "globals": {
    "include": {},
    "exclude": { "classification": ["government"] }
  },
  "sections": [
    { "id": "statewide_spend", "type": "bias_gauge",
      "params": { "window_days": 7 } },
    { "id": "cumulative", "type": "cumulative_spend",
      "params": { "interval": "week", "top_affiliations": 8 } },
    { "id": "messaging", "type": "messaging_tone",
      "params": { "window_days": 28, "top_themes": 5,
        "cards": [
          { "label": "Labor",   "affiliation_ids": ["aff_labor"] },
          { "label": "Liberal", "affiliation_ids": ["aff_liberal"] },
          { "label": "Greens",  "affiliation_ids": ["aff_greens"] },
          { "label": "Teals",   "affiliation_ids": ["aff_climate_200"] }
        ] } },
    { "id": "top_seats", "type": "top_seats",
      "params": { "limit": 10, "windows": [7, 28], "rank_by_window": 7 },
      "include": { "classification": ["political participant"] } }
  ]
}
```

Property types in v1: `date`, `enum`, `string`, `number`, `affiliation_list`.

Subject placeholders available in v1: `{jurisdiction_label}` (e.g. "Victorian state", "Federal"),
`{as_of_long}` (e.g. "1 October 2026"), `{window_start_long}`, `{template_name}`, `{record_name}`.

### 3.2 Dispatch Record (`dispatch_records/<auto id>`, default database)

```json
{
  "name": "VIC election weekly brief",
  "template_id": "weekly_campaign_brief",
  "template_schema_version": 1,
  "property_values": { "start_date": "2026-07-01", "end_date": "2026-11-28",
                       "jurisdiction": "state", "state": "VIC" },
  "recipients": ["talis.evans@gmail.com", "james@stvns.com"],
  "contact_email": null,
  "schedule": { "preset": "weekly", "days": ["mon"], "time": "09:00" },
  "cron": "0 9 * * 1",
  "timezone": "Australia/Melbourne",
  "start_delivery": "2026-10-01",
  "end_delivery": "2026-11-28",
  "status": "active",
  "scheduler_job": "projects/advance-campaign-app/locations/australia-southeast1/jobs/dispatch-<id>",
  "last_run": { "slot": "2026-10-05T09:00", "at": "...", "outcome": "sent",
                "error": null, "recipient_count": 2, "failed_recipients": [] },
  "created_at": "...", "created_by": "...", "updated_at": "...", "updated_by": "..."
}
```

- `contact_email`: null means use `created_by`.
- `schedule.preset` is `daily` or `weekly`. `days` holds `mon` to `sun`, used for `weekly` only.
  `time` is `HH:MM` on the quarter hour.
- `timezone` is an IANA name. The UI offers the eight Australian capital zones.
- `start_delivery` and `end_delivery` are inclusive dates read in the record's timezone.
- `status` is `active` or `inactive`.
- `last_run.outcome` is `sent`, `partial`, `failed` or `skipped`.

### 3.3 Run ledger (`dispatch_records/<id>/runs/<slot>`)

```json
{
  "slot": "2026-10-05T09:00",
  "kind": "scheduled",
  "started_at": "...", "finished_at": "...",
  "as_of": "2026-10-01",
  "outcome": "partial",
  "recipients": { "talis.evans@gmail.com": { "status": "sent", "message_id": "..." },
                  "james@stvns.com":       { "status": "failed", "error": "..." } },
  "archive_prefix": "sent/<id>/2026-10-05T09:00/",
  "expire_at": "<started_at + 30 days>"
}
```

- `kind` is `scheduled` or `manual`. Manual slots are named `manual-<UTC timestamp>`.
- A Firestore TTL policy on the `runs` collection group, field `expire_at`, removes documents
  after 30 days.
- Test sends write no ledger and do not change `last_run`.

### 3.4 Catalogue (`dispatch_catalogue/<doc>`, default database)

Written only by `publish-templates`, generated from the job's pydantic models. Read by the MCP tools.

- `dispatch_catalogue/template_schema`: JSON Schema for a template, the filter registry (key,
  kind, source column or table, implemented yes or no), property types, subject placeholders,
  authoring rules (section 9.2), and the Weekly Campaign Brief as an annotated example.
- `dispatch_catalogue/section_types`: for each section type, its description, params JSON Schema,
  what it renders, and every template and section `id` that uses it with that instance's config.

### 3.5 Bucket layout (`gs://advance_dispatch`)

```
templates/emails/<template_id>/layout.html.j2
templates/emails/<template_id>/sample.html
templates/sections/<type>/<type>.html.j2      read-only copy; the job renders from the image
templates/sections/<type>/sample.html
sent/<record_id>/<slot>/email.html
sent/<record_id>/<slot>/browser.html
sent/<record_id>/<slot>/<chart_name>.png
```

Lifecycle rule: delete objects under `sent/` 30 days after creation.

## 4. Phase 1: job skeleton, schema and publish tool (`AdVance-dispatch`)

### 4.1 Repo layout

```
AdVance-dispatch/
  pyproject.toml
  Dockerfile
  deploy/deploy.sh
  src/dispatch/
    main.py                 entry point and argument parsing
    config.py               project, buckets, secret names, database names
    models/
      template.py           pydantic: Template, PropertyDefinition, FilterSet, SectionConfig
      record.py             pydantic: DispatchRecord, Schedule, LastRun
      ledger.py             pydantic: RunLedger
    filters/
      registry.py           every filter key, its kind and source
      compile.py            FilterSet to DuckDB WHERE clause and bound parameters
    data/
      gold.py               download gold parquet and caches, open DuckDB, create views
      reference.py          biases, affiliations, colours, merges
      as_of.py              the as_of date and the Google completeness check
    sections/
      base.py               Section protocol, SectionContext, SectionResult
      bias_gauge.py         + bias_gauge.html.j2
      cumulative_spend.py   + cumulative_spend.html.j2
      messaging_tone.py     + messaging_tone.html.j2
      top_seats.py          + top_seats.html.j2
      registry.py           section type name to module
    charts/
      style.py              fonts, sizes, 2x density
      gauge.py              half doughnut
      lines.py              cumulative line chart
    render/
      layout.py             fetch layout from bucket, Jinja2 environment
      inline.py             premailer CSS inlining
      email_skeleton.html.j2  shared Outlook-safe outer frame
    delivery/
      ses.py                SMTP over the aws_ses secret
      message.py            MIME build: HTML, plain text, CID images, Reply-To
      archive.py            upload, signed browser URL
    scheduling/
      slots.py              current slot from cron and timezone
      scheduler.py          delete own trigger after end_delivery
    run.py                  one record, end to end
    publish_templates.py    the publish-templates command
  templates/weekly_campaign_brief/
    template.json
    layout.html.j2
  tests/
    fixtures/gold/          small parquet set with known values
    fixtures/lookups/
```

Follow the longform conventions: full names, one plain comment above each block, banner
headings, docstring on every function and class.

### 4.2 Template and record models

- `Template` mirrors section 3.1. `schema_version` must be one the job supports (a constant,
  `SUPPORTED_SCHEMA_VERSIONS = {1}`).
- `PropertyDefinition.required_when` is a map of other property key to required value.
- `Template.validate_property_values(values)` checks presence, type, enum membership and
  `required_when`. Used by the job at run time. The API holds an equivalent TypeScript check.
- Each section's `params` is validated against that section type's own params model, so a typo
  in a template fails at publish time, not at 9am Monday.

### 4.3 Filter registry (`filters/registry.py`)

| Key | Kind | Source | v1 |
|---|---|---|---|
| `classification` | select | `adverts.creator_classification` | yes |
| `affiliation_id` | select | `adverts.creator_affiliation_id` | yes |
| `bias` | select | `adverts.creator_affiliation_bias` | yes |
| `creator_id` | select | `adverts.creator_id` | yes |
| `datasource` | select | `adverts.datasource` | yes |
| `approach` | select | `adverts.approach` | yes |
| `theme` | select | `adverts.themes` (any match) | yes |
| `is_local_government_content` | select | `adverts.is_local_government_content` | yes |
| `age_range` | weight | `ad_demo` | registered, not implemented |
| `gender` | weight | `ad_demo` | registered, not implemented |
| `platform` | weight | `ad_platform` | registered, not implemented |
| `electorate_id` | weight | `ad_geo` | registered, not implemented |

- A template naming an unimplemented key fails validation with a message naming the key.
- `null` in a value list compiles to `IS NULL` OR'd with the `IN` list.
- `affiliation_id` values are resolved through `affiliation_superseded_by` before compiling, so a
  merged affiliation keeps matching.
- `compile.py` returns a SQL fragment over an `adverts` alias plus a parameter list. No string
  interpolation of values.
- Implementing a `weight` key later: add a join to the matching apportioned view and multiply the
  section's spend by the matched share (include) or one minus it (exclude). Age and gender must
  share one join, as ADR 0006 requires.

### 4.4 `publish-templates`

```
python -m dispatch.publish_templates [--template <id>] --dry-run         (anywhere)
python -m dispatch.main publish-templates --build-tag <tag>              (inside the image only)
```

1. Load every `templates/emails/*/template.json` and validate it.
2. Render each template against the test fixtures, to catch layout and partial errors.
3. Render samples: one per email template, one per section type, from made-up data, with charts
   described in words and a notice that the figures are not real.
4. Upload layouts, partial copies and samples to `gs://advance_dispatch/templates/` (section 3.5).
5. Upsert `dispatch_templates/<id>`, stamped with the build tag.
6. Write `dispatch_catalogue/template_schema` and `dispatch_catalogue/section_types`, stamped with
   the build tag. They name samples and partials by bucket path; the bucket holds the one copy.

`--dry-run` does steps 1 to 3. A real publish refuses to run outside Cloud Run. `deploy/deploy.sh`
runs it as one execution of the job (`gcloud run jobs execute ... --args=publish-templates,...`)
after pointing the job at the new image, so what is published always matches what the job runs.

## 5. Phase 2: the job (`AdVance-dispatch`)

### 5.1 Entry point

```
python -m dispatch.main --record-id <id> [--manual] [--test-recipient <email>]
```

Scheduler passes `--record-id` only. The API passes `--manual` for "Send now" and
`--test-recipient` for "Send test to me".

### 5.2 Run flow (`run.py`)

1. Load the record. If missing, exit 0 with a log line (a trigger outliving its record).
2. Unless test or manual: if `status` is `inactive`, exit 0. If today (in the record's timezone)
   is before `start_delivery`, exit 0. If after `end_delivery`, delete the trigger
   `dispatch-<id>`, set `last_run.outcome` to `skipped`, and exit 0.
3. Work out the slot. Scheduled: the most recent cron fire time at or before now, in the record's
   timezone (`croniter`), formatted `YYYY-MM-DDTHH:MM`. Manual: `manual-<UTC timestamp>`. Test: no
   slot.
4. Load the template from Firestore and the layout from the bucket. Check `schema_version`
   against both the job and the record. Validate `property_values`.
5. Download gold and the lookup caches (section 5.3). Compute `as_of` (section 5.4).
6. Build each section in order. A section that raises fails the whole run: a brief with a hole in
   it is worse than a late one.
7. Render the email HTML (CID image references) and the browser HTML (base64 images). Inline CSS
   on both.
8. Upload the archive and sign the browser URL. Test sends archive under `sent/<id>/test-<UTC>/`.
9. Read the ledger for the slot. Send to each recipient not already marked `sent`, recording each
   outcome in the ledger as it happens.
10. Write `last_run`. Record nothing in `runtime_completions`.
11. Exit non-zero if any recipient failed or anything raised.

### 5.3 Data access (`data/gold.py`, `data/reference.py`)

- Download the seven gold parquet files from `gs://advance_gold` and the caches `affiliations`,
  `bias_definitions` and `content_creators` from `gs://advance_lookups/caches/`.
- Create the apportioned views with the same definitions as `AdVance-api/lib/duck.ts:62`
  (`ad_geo_daily`, `ad_state_daily`). Copy, do not import; add a test that compares one figure
  against the API's to catch drift.
- Every query applies the hard jurisdiction filter first (ADR 0001).
- For `jurisdiction: state`, statewide figures come from `ad_state_daily` where `state` is the
  record's state. Seat figures come from `ad_geo_daily` joined to `electorates` on that state.
- For `jurisdiction: federal`, statewide figures are national unless `state` is set.
- Affiliation colour comes from `affiliations.colour`. When null, fall back to the same
  deterministic palette as `AdVance-front-end/src/app/shared/palette.ts`, ported to Python, so
  the email matches the dashboard.
- Never sum themes across an advert (ADR 0003).

### 5.4 `as_of` (`data/as_of.py`)

```sql
SELECT max(daily.date)
FROM ad_daily AS daily
JOIN adverts USING (ad_key)
WHERE adverts.datasource = 'meta'
```

- Window end is `min(as_of, property_values.end_date)`.
- An N-day window is `window_end - (N - 1)` to `window_end`, inclusive.
- Google check: if `max(date)` for Google adverts is earlier than the window end, add the callout
  "Google data is incomplete after <date>. Figures for those days include Meta only."

Worked example on a 3 Oct 2026 run: Meta's latest date is 1 Oct, so the 7-day window is
25 Sep to 1 Oct and the 28-day window is 4 Sep to 1 Oct.

### 5.5 Section contract (`sections/base.py`)

```python
class SectionContext:
    """Everything a section needs: DuckDB connection, record, filters, dates and reference data."""

class SectionResult:
    """What a section returns: template variables, chart images and footnotes."""
    variables: dict
    images: list[ChartImage]     # name, png bytes, display width
    notes: list[str]
```

Each section module exposes `TYPE_NAME`, `Params` (pydantic), `DESCRIPTION`, `RENDERS`
(one-line summary for the catalogue), `PARTIAL` (partial file name) and `build(context, params)`.
The combined filter (global plus section) is already in `context.filter_sql`.

### 5.6 `bias_gauge`

Params: `window_days` (default 7).

1. Spend in the window grouped by `creator_affiliation_bias`, with classification `government`
   always excluded on top of the template's filters.
2. Join `bias_definitions` for position and colour. Null bias becomes `unmapped` at position 0,
   colour `#d1d5db`, ordered straight after `centrist`.
3. Totals: Left (position below 0), Centre and unmapped (position 0), Right (position above 0),
   and grand total.
4. Chart: half doughnut PNG, segments left to right by position.
5. Legend: table rows of swatch, bias name and spend.
6. Note: "Government advertising is excluded from bias figures."

### 5.7 `cumulative_spend`

Params: `interval` (`week` only in v1), `top_affiliations` (default 8).

1. Weekly cumulative spend from `start_date` to the window end, government excluded as in 5.6.
2. Left chart: one line per bias, bias colours, unmapped in grey.
3. Right chart: the top N affiliations by cumulative total, then Other (the rest), then Unmapped
   (null affiliation). Other is `#9ca3af`, Unmapped `#d1d5db`.
4. Under each chart, a table of name, swatch and cumulative total, highest first.
5. Two-column hybrid layout: side by side at 640px, stacked on clients that honour media queries.

### 5.8 `messaging_tone`

Params: `window_days` (default 28), `top_themes` (default 5), `cards` (list of `label`,
`affiliation_ids`, optional `colour`).

1. For each card, spend in the window for adverts whose affiliation is in the card's list.
2. Tone split by `approach`: positive, compare and contrast, negative, unclassified (null). Shares
   of the card's spend.
3. Top themes by spend, each theme counted in full for every advert carrying it.
4. Order cards by spend, highest first. Cards with zero spend go last, greyed, reading "No
   advertising in the last 28 days".
5. Note: "One ad can cover several issues, so issue amounts overlap and should not be added
   together."

### 5.9 `top_seats`

Params: `limit` (default 10), `windows` (default `[7, 28]`), `rank_by_window` (default 7).

1. Spend per seat per spender in each window, from `ad_geo_daily`, restricted to the record's
   jurisdiction and state.
2. Spender key: `affiliation_id`, or `creator:<creator_id>` when the affiliation is null.
   Display name: affiliation name, or creator name with an "unmapped" tag.
3. Rank seats by total spend in the ranking window. Take `limit`.
4. In each seat, rank spenders by spend in the ranking window. Ties break on spender key. Show the
   leader and runner-up with their spend. Runner-up reads "none" when there is only one.
5. Columns: rank, seat, margin (only if the seat lookup exists, D21), leader, runner-up, 7-day
   total, 28-day total.

Worked example: Kew, 7 days. Teal (`aff_climate_200`) $4,487, Liberal $864, unmapped Jane Smith
$600, unmapped Bob Lee $500. Leader Teal $4,487, runner-up Liberal $864. The two independents are
not merged.

### 5.10 Charts (`charts/`)

- matplotlib with the Agg backend, no display needed.
- Render at 2x the display width (580px for a 290px chart), PNG, transparent background off
  (Outlook draws transparent PNGs on black in some dark modes).
- Fonts: Arial or a bundled Liberation Sans so rendering does not depend on the container.
- Every chart has `alt` text that states its key figures, for clients that block images.

### 5.11 HTML and email build (`render/`, `delivery/`)

- `email_skeleton.html.j2` is the shared Outlook-safe frame: `<!--[if mso]>` 640px table, inner
  tables with `role="presentation"`, inline styles only, `bgcolor` attributes alongside CSS
  backgrounds, no margins on block elements (use cell padding), web-safe fonts.
- The template layout extends the skeleton and loops over sections, including each partial.
- First line inside the frame: "Not displaying properly? View it in your browser." linking to the
  signed URL.
- Footer: data source line, the window sentence from D16, and "To stop receiving these emails,
  contact <contact email>."
- `premailer` inlines CSS on both renders.
- MIME: `multipart/related` holding `multipart/alternative` (plain text summary plus HTML) and
  the PNGs with `Content-ID` headers.
- Plain text part: headline figures, the window sentence and the browser link.
- Headers: `From: AdVance Dispatch <no-reply@talisevans.dev>`, `To:` one recipient, `Reply-To:`
  the contact, `Subject` from the template.

### 5.12 Archive and signed URL (`delivery/archive.py`)

- Cloud Run credentials hold no private key, so signing goes through the IAM `signBlob` API:
  call `Blob.generate_signed_url(version='v4', service_account_email=..., access_token=...)`.
  The job's service account needs `roles/iam.serviceAccountTokenCreator` on itself.
- Expiry: 7 days, the V4 maximum.
- Sign first, then upload, then send.

### 5.13 Tests (pytest)

- Fixture gold: a few dozen adverts across two states and both jurisdictions, with values chosen
  so every section's figures can be checked by hand.
- One test per section for its figures, including: government dropped from the gauge, unmapped at
  position 0, Other and Unmapped in the cumulative right column, zero-spend card kept, unmapped
  independents not merged in Top Seats, tie order stable.
- Filter compile tests: include, exclude, `null`, section narrowing global, superseded
  affiliation, unimplemented weight key rejected.
- `as_of` tests: Meta latest date wins; `end_date` caps it; Google callout appears only when
  Google stops before the window end.
- Slot tests: daylight saving change in Melbourne, weekly on Monday, rerun finds the same slot.
- Ledger test: rerun after a partial send only sends to the failed recipient.
- Snapshot test of the full Weekly Campaign Brief render against fixtures.
- Apportioned view parity test against a figure from the API's views.

## 6. Phase 3: API (`AdVance-api`)

### 6.1 Routes

All behind `adminRoute` (`lib/admin/route.ts`).

| Method and path | Does |
|---|---|
| `GET /api/admin/dispatch/templates` | List templates: id, name, description, `required_properties`, `schema_version`. |
| `GET /api/admin/dispatch/records` | List records. `?tab=active` (end_delivery today or later) or `?tab=expired`. |
| `GET /api/admin/dispatch/records/[id]` | One record plus its last 10 ledger entries. |
| `POST /api/admin/dispatch/records` | Create. Validates, writes, creates the trigger. |
| `PUT /api/admin/dispatch/records/[id]` | Update. Validates, writes, updates or recreates the trigger, pauses or resumes it. |
| `DELETE /api/admin/dispatch/records/[id]` | Delete record, ledger and trigger. |
| `POST /api/admin/dispatch/records/[id]/duplicate` | Return a copy as an unsaved draft (no id, no `last_run`). |
| `POST /api/admin/dispatch/records/[id]/send` | Body `{ "mode": "test" }` or `{ "mode": "now" }`. Starts a job execution with the matching args. |

"Today" for the tab split is evaluated in each record's own timezone.

### 6.2 Validation (`lib/admin/dispatch/record-rules.ts`)

- Template exists and its `schema_version` equals the record's.
- `property_values` satisfy `required_properties`, including `required_when`.
- 1 to 50 recipients, each a valid address, lowercased, duplicates removed.
- `contact_email` null or a valid address.
- `schedule` valid; cron derived from it (section 6.3).
- `timezone` is one of the offered IANA names.
- `start_delivery` on or before `end_delivery`. On create, `end_delivery` is today or later.
- `status` is `active` or `inactive`.

### 6.3 Schedule to cron (`lib/admin/dispatch/schedule.ts`)

- `daily` at `HH:MM` becomes `MM HH * * *`.
- `weekly` on days D at `HH:MM` becomes `MM HH * * D`, days numbered Monday `1` to Saturday `6`
  and Sunday `0`, joined by commas. Example: Monday and Thursday at 09:00 is `0 9 * * 1,4`.
- Unit tests for each preset and every day.

### 6.4 Scheduler client (`lib/admin/dispatch/scheduler.ts`)

Same shape as `lib/admin/etl-job.ts`: an interface with a real implementation over the REST API
and a fake for tests.

- `upsert(recordId, cron, timezone, paused)`: create or patch job `dispatch-<recordId>` in
  `australia-southeast1`. HTTP target `POST https://run.googleapis.com/v2/projects/advance-campaign-app/locations/australia-southeast1/jobs/advance-dispatch:run`
  with body `{"overrides":{"containerOverrides":[{"args":["--record-id","<id>"]}]}}` and an
  OAuth token for the `advance-dispatch-invoker` service account.
- `pause` and `resume` on status change.
- `delete` on record delete. A missing trigger is not an error.
- Retry config: at most 1 retry, 5 minutes later. The ledger makes the retry safe.
- On save, Firestore is written first, then the trigger. If the trigger call fails, the record is
  saved with `scheduler_error` set and the pane shows "Saved, but scheduling failed. Save again to
  retry."

### 6.5 Send now and test (`lib/admin/dispatch/send.ts`)

Calls the Cloud Run Admin API `jobs:run` on `advance-dispatch` with args overrides, the same
pattern as `runEditsOnly()` in `lib/admin/etl-job.ts`.

- Test: `--record-id <id> --test-recipient <admin email from the auth context>`.
- Now: `--record-id <id> --manual`.
- Returns the execution name. The pane shows a confirmation; it does not poll.

### 6.6 MCP tools (`lib/mcp/tools/dispatch.ts`)

Registered in `createMcpServer()` beside the existing tools. Read-only. Available to every
allowlisted MCP user.

- `dispatch_template_guide`: returns `dispatch_catalogue/template_schema`. Description tells the
  model to call it before proposing a new template, and to prefer existing section types.
- `list_dispatch_sections`: returns `dispatch_catalogue/section_types`. Optional `type` argument
  narrows to one section type.
- `list_dispatch_records`: returns every record with `recipients`, `contact_email`,
  `created_by`, `updated_by`, `last_run.failed_recipients` and the ledger removed. Adds
  `recipient_count`. Optional `include_expired` (default false).

Add a line to the server `instructions` pointing at the three tools for anyone designing a new
email briefing.

### 6.7 Tests (vitest)

- Record rules, including every `required_when` case and the 50 recipient cap.
- Schedule to cron for every preset.
- Route tests with the fake Scheduler client: create makes a trigger, `inactive` pauses it,
  delete removes it, a failed trigger call leaves `scheduler_error`.
- MCP `list_dispatch_records` output contains no `@` character anywhere (assert on the serialised
  output), so no address can leak.

### 6.8 HTTP contract

Add a Dispatch section to `AdVance-api/docs/admin-api-contract.md`.

## 7. Phase 4: front end (`AdVance-front-end`)

### 7.1 Navigation and routes

- Add `{ path: 'dispatch', label: 'Dispatch', icon: 'mail' }` to `settingsTabs`
  (`src/app/shell/shell.component.ts:157`). Admin only, as the other settings tabs.
- Add `settings/dispatch` under the existing `adminGuard` block in `src/app/app.routes.ts`.

### 7.2 Dispatch list (`src/app/settings/dispatch/dispatch-list.component.*`)

- Two tabs: Active and Expired.
- Columns: name, template, jurisdiction and state, schedule in words ("Mondays 9:00 AEST"),
  delivery window, recipients count, status badge (Active, Paused), last run (time and outcome).
- Row actions: edit (opens pane), duplicate (opens pane with the draft), delete (confirm dialog
  from `settings/shared/confirm-dialog`).
- "New Dispatch" button opens the pane empty.

### 7.3 Edit pane (`src/app/settings/dispatch/dispatch-edit-pane.component.*`)

Wraps `app-side-pane`, like `creator-edit-pane`.

1. Name.
2. Template select. Changing it rebuilds the property fields.
3. Property fields, generated from `required_properties` in order. `date` is a date input, `enum`
   a select, `affiliation_list` a multi-select over live affiliations. Fields whose
   `required_when` is not met are hidden and cleared.
4. Recipients: a chip input. Validates each address and shows the count against 50.
5. Contact email: optional, placeholder shows the creator's address.
6. Schedule: Daily or Weekly; for Weekly, day toggles Monday to Sunday; time select in 15 minute
   steps; timezone select. A sentence under it reads back the schedule in words.
7. Delivery window: start and end dates.
8. Status toggle.
9. Buttons: Save, Send test to me, Send now (confirm: "Send to all N recipients now?"). The send
   buttons are disabled until the record is saved and has no unsaved changes.
10. Recent runs: the last 10 ledger entries with slot, outcome and failed addresses.

Rules (required fields, address format, cap, dates) live in `dispatch-rules.ts` with specs, as
the other settings pages do.

### 7.4 Service

Add the dispatch calls to `src/app/services/admin-api.service.ts`.

## 8. Phase 5: the Weekly Campaign Brief template

1. Split `vic_election_weekly_briefing.html` into the shared skeleton, `layout.html.j2` (header,
   section loop, footer) and the four section partials.
2. Replace every inline figure with template variables.
3. Replace the gauge and cumulative SVGs with PNG `img` tags referencing CIDs.
4. Replace flexbox and grid with tables. Messaging cards become a two-column hybrid table.
5. Keep the visual identity: navy `#002147` rules, serif title, Arial body.
6. Write `template.json` (section 3.1).
7. Prerequisite data fix: map Sophie Torney's and Shima Ibuki's creators to `aff_climate_200` in
   Creator Mapping, then Publish.
8. Publish with `publish-templates`, create a VIC record, send a test, compare against the
   original HTML.

## 9. Infrastructure, deploy and documentation

### 9.1 Infrastructure (one-off, `AdVance-dispatch/deploy/deploy.sh setup`)

- Service account `advance-dispatch@advance-campaign-app.iam.gserviceaccount.com` (runs the job):
  - `roles/storage.objectViewer` on `advance_gold` and `advance_lookups`.
  - `roles/storage.objectAdmin` on `advance_dispatch`.
  - `roles/datastore.user` on the project.
  - `roles/secretmanager.secretAccessor` on `aws_ses`.
  - `roles/cloudscheduler.admin` (to delete its own trigger after `end_delivery`).
  - `roles/iam.serviceAccountTokenCreator` on itself (signed URLs).
- Service account `advance-dispatch-invoker@...` (used by Scheduler triggers):
  - `roles/run.invoker` on the `advance-dispatch` job.
- API runtime service account `advance-api@...`:
  - `roles/cloudscheduler.admin`.
  - `roles/iam.serviceAccountUser` on `advance-dispatch-invoker` (to attach it to triggers).
  - `roles/run.developer` on the `advance-dispatch` job (to run it with overrides), unless its
    existing grant for `campaign-ads-etl` is project-wide.
- Cloud Run job `advance-dispatch`, region `australia-southeast1`, 2 GiB memory, 15 minute
  timeout, max retries 0 (the Scheduler retry and the ledger cover reruns).
- Artifact Registry repository for the image, keep last 2.
- Firestore TTL policy on collection group `runs`, field `expire_at`.
- Bucket lifecycle rule on `advance_dispatch`: delete `sent/` objects older than 30 days.
- The existing "Cloud Run Job Failure" alert policy already covers every job in the project.
  Confirm it matches `advance-dispatch`.

### 9.2 Authoring rules (shipped in `dispatch_template_guide`)

- Reuse an existing section type when its params can express the need. Add params before adding a
  type.
- Never put jurisdiction or state in a template's filters; they come from the record.
- Use ids, never display names, in filters and cards.
- Themes overlap; never sum them.
- Respect the as_of window; never use the run date for data.
- Charts must be PNG; everything else must be table markup.

### 9.3 Deploy

`AdVance-dispatch/deploy/deploy.sh deploy`: run tests, build the image with Cloud Build, move the
`latest` tag, update the job, run `publish-templates`.

### 9.4 Documentation

- `AdVance-dispatch/README.md`: how to add a template, how to add a section type, how to run
  locally against the parquet mirror, how to send a test.
- Add Dispatch Template, Dispatch Record, Dispatch, Slot and As-of date to the workspace glossary.
- ADR 0008: "Dispatch schedules are per-record Cloud Scheduler triggers owned by the API."

## 10. Phase 6: acceptance

1. `publish-templates --dry-run` passes; then a real publish writes the template and both catalogue
   documents.
2. Create a VIC record for Monday 9:00 Melbourne time. The trigger appears with the right cron and
   timezone.
3. Send test to me. The email arrives in Gmail, Apple Mail and Outlook.com. Charts show without a
   "load images" prompt where the client allows it. The browser link opens the archived copy.
4. Check every figure against the MCP `query` tool for the same window and filters.
5. Pause the record: the trigger is paused. Resume: it is enabled.
6. Force a failure for one recipient (an invalid domain). Outcome is `partial`, the failure alert
   fires, and a rerun of the same slot sends only to that recipient.
7. Set `end_delivery` to yesterday and trigger the job by hand. It deletes its trigger and marks
   the run `skipped`. Move `end_delivery` forward and save: the trigger is back.
8. Call the three MCP tools. `list_dispatch_records` contains no addresses.
9. After 30 days, the archive and ledger entries are gone.

## 11. Order of work

1. Phase 1 (models, registry, publish tool) with tests.
2. Phase 2 (job and sections) against fixtures, then against the live parquet mirror.
3. Phase 5 (Weekly Campaign Brief) alongside phase 2, since it drives the section design.
4. Phase 3 (API and MCP).
5. Phase 4 (front end).
6. Section 9 infrastructure, then phase 6 acceptance.

## 12. Out of scope

- A UI for creating or editing templates.
- Implementing the `weight` filter keys (age, gender, platform, electorate).
- Self-service unsubscribe links.
- Open and click tracking.
- An in-browser HTML preview.
- Schedules more frequent than daily.

## 13. Known limits and dependencies

- **Seat margins** are parked as a separate back-end project, to be planned in
  `AdVance-back-end/plans/`: a `advance_lookups` parquet of every federal and state seat with
  current member, affiliation, margin and the date of the election they won, possibly sourced from
  Wikipedia (the members refresh jobs already parse Wikipedia rosters). Top Seats hides the Margin
  column until it exists.
- **Signed browser links expire after 7 days**, a hard limit of Google's V4 signing. The archive
  itself is deleted after 30 days.
- **Signed browser links can be forwarded.** Anyone holding one can read that email for 7 days.
- **`as_of` follows Meta.** On a day Google is partly loaded, the last day's Google figures are
  partial. On the 3 Oct 2026 data this understated the Victorian 7-day total by about 1%.
- **Section and API view definitions are copied, not shared.** The parity test in 5.13 catches
  drift.
- **One trigger per record** costs US$0.10 a month each beyond the account's 3 free triggers.
