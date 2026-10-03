# AdVance Dispatch

Scheduled HTML email briefings built from AdVance gold data.

- A **Dispatch Template** (written by a developer, in `templates/emails/<id>/`) says what an email
  contains, which properties a record must supply, and how each section filters the data.
- A **Dispatch Record** (created by an admin in the web app, stored in Firestore
  `dispatch_records`) picks a template, fills in its properties, and sets recipients, schedule and
  delivery window.
- A **Dispatch** is one email, built by this Cloud Run job when a record's Cloud Scheduler trigger
  fires.

The binding design is `plan/2026-10-03_implementation_plan.md`. The contracts section authors build
on are in `plan/CONTRACTS.md`.

## Layout

```
src/dispatch/
  main.py               entry point: --record-id, --manual, --test-recipient, --render-only, publish-templates
  preview.py            local render to disk with fakes for every cloud service
  run.py                one record end to end: window checks, slot, build, archive, send, ledger
  build.py              build sections and render the email, browser copy and plain text
  publish_templates.py  validate, render samples, upload layouts, partial copies and samples, write the catalogue
  config.py             project, buckets, secrets, collections, environment variables
  formatting.py         money, percentages and dates, also available as Jinja2 filters
  models/               pydantic: Template, DispatchRecord, RunLedger
  filters/              the filter registry and FilterSet to SQL compiler
  data/                 gold in DuckDB, reference data and colours, as_of and windows
  sections/             base.py (the contract), registry.py, one folder per type holding its module and partial
  charts/               style.py (shared chart style), one module per chart kind
  render/               email_skeleton.html.j2, shared CSS, layout rendering, CSS inlining, samples
  delivery/             MIME building, SES over SMTP, archive and signed browser link
  scheduling/           slots from cron, deleting the record's own trigger
  store/                Firestore behind an interface, with an in-memory fake
templates/emails/<id>/  template.json, layout.html.j2 and an example_record.json for previews
tests/                  pytest, with fixtures in tests/fixtures
deploy/deploy.sh        setup (one-off infrastructure) and deploy
```

## Getting started

```
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps -e .
pytest
```

`requirements.txt` pins every package to an exact version. The image (`python:3.14-slim`)
installs from the same file, so local runs and the job use identical versions. To upgrade a
package, change its pin, reinstall, run the tests, and rebuild the image.

## How to add a template

1. Create `templates/emails/<template_id>/template.json`. The id is a lower-case slug and must match
   the folder name. `layout_path` must be `templates/emails/<template_id>/layout.html.j2`. The shape is in
   plan section 3.1; `plan/CONTRACTS.md` lists the property types, subject placeholders and filter keys.
2. Create `templates/emails/<template_id>/layout.html.j2`. It extends `email_skeleton.html.j2` and fills
   the `header` block. The skeleton already loops over the sections and includes each partial;
   override the `sections` block only to change that.
3. Reuse existing section types where their params can express the need. Never put jurisdiction or
   state in filters: they come from the record.
4. Validate and render it against the fixtures:

   ```
   .venv/bin/python -m dispatch.publish_templates --template <template_id> --dry-run
   ```

5. Publish with `deploy/deploy.sh deploy`. A real publish runs only inside the deployed image (see
   "Publishing" below), so it cannot be run from your machine.

## Publishing

`deploy/deploy.sh deploy` builds the image, points the job at it, then runs
`publish-templates` as one execution of the job:

```
gcloud run jobs execute advance-dispatch --args=publish-templates,--build-tag,<tag> --wait
```

Running inside the image means everything published comes from the code and templates the job
sends with. The publish refuses to run anywhere else (it checks for Cloud Run's `CLOUD_RUN_JOB`
variable) and needs the image's build tag, which it stamps on every document. It writes:

```
gs://advance_dispatch/templates/
  emails/<id>/layout.html.j2        the layout the job reads at send time
  emails/<id>/sample.html           the whole email, made-up figures, charts described in words
  sections/<type>/<type>.html.j2    read-only copy of the partial (the job uses the one in the image)
  sections/<type>/sample.html       the section alone, made-up figures, charts described in words
Firestore dispatch_templates/<id>   the template, with build_tag and sample_path
Firestore dispatch_catalogue/*      template_schema and section_types, naming each file by bucket path
```

Samples are rendered from `tests/fixtures`, which the image carries for this purpose, and open with
a notice that their figures are made up. The bucket holds the one copy of each file. The MCP tools
`list_dispatch_sections` and `dispatch_template_guide` read the catalogue from Firestore, then
download a sample or partial from the bucket when one is asked for, signed in as the API's own
service account, and return its text in the tool result.

To see the samples locally without publishing, run the dry run: it renders them and writes nothing.

## How to add a section type

1. Create the folder `src/dispatch/sections/<type>/` with an `__init__.py`, and write
   `src/dispatch/sections/<type>/<type>.py` keeping the contract in `plan/CONTRACTS.md`: `TYPE_NAME`,
   `Params`, `DESCRIPTION`, `RENDERS`, `PARTIAL` and `build(context, params)`.
2. Write its partial `src/dispatch/sections/<type>/<type>.html.j2` beside it. A partial renders one or more
   `<tr>` rows of the 640px container table, with table markup and inline styles only.
3. Register it in `src/dispatch/sections/registry.py`:

   ```python
   from dispatch.sections.bias_gauge import bias_gauge

   SECTION_TYPES = {
       bias_gauge.TYPE_NAME: bias_gauge,
   }
   ```

4. Add tests that assert its figures against `tests/fixtures/README.md`.

## How to run locally against the parquet mirror

The API keeps a mirror of gold at `/tmp/advance-gold`, with the lookup caches in
`/tmp/advance-gold/lookups`. Point the job at it instead of the buckets:

```
export DISPATCH_GOLD_DIR=/tmp/advance-gold
export DISPATCH_LOOKUPS_DIR=/tmp/advance-gold/lookups   # optional; this is the default
```

The fixtures work the same way:

```
export DISPATCH_GOLD_DIR=tests/fixtures/gold
export DISPATCH_LOOKUPS_DIR=tests/fixtures/lookups
```

A full run still reads the record and template from Firestore, archives to the Dispatch bucket and
sends through SES. To read layouts from the repository instead of the bucket, add
`--layout-dir .`:

```
.venv/bin/python -m dispatch.main --record-id <id> --test-recipient you@example.com --layout-dir .
```

To build and render without sending anything, use the dry run above, which renders every template
against the fixtures, or the local preview below.

## How to preview a Dispatch locally

`--render-only` runs the real job path for one record with local stand-ins for every cloud service:
the record comes from a JSON file, the template and layout from `templates/`, gold from a local
parquet directory, and Firestore, the archive bucket, SES and Cloud Scheduler are in-memory fakes.
Nothing is read from or written to Google Cloud, and nothing is sent. It runs as a "Send now" run,
so the delivery window is ignored.

Against the API's parquet mirror:

```
.venv/bin/python -m dispatch.main --render-only \
  --record-file templates/emails/weekly_campaign_brief/example_record.json \
  --data-dir /tmp/advance-gold \
  --out out/
```

Against the test fixtures (their lookups sit outside the gold folder, so name them):

```
.venv/bin/python -m dispatch.main --render-only \
  --record-file templates/emails/weekly_campaign_brief/example_record.json \
  --data-dir tests/fixtures/gold --lookups-dir tests/fixtures/lookups \
  --out out/
```

`--lookups-dir` defaults to `<data-dir>/lookups`. The record file has the shape of plan section 3.2;
`id` is optional. The command writes:

| File | What it is |
|---|---|
| `browser.html` | The browser copy, charts embedded. Open this one in a browser. |
| `email.html` | The email copy. Charts are `cid:` references, so they show only in a mail client. Its "view in browser" link opens `browser.html` beside it. |
| `<section>-<chart>.png` | Each chart image. |
| `email.txt` | The plain-text part. |
| `message.eml` | The whole MIME message for the first recipient. Open it in Apple Mail or Outlook to see the email as sent. |

## Snapshot tests

`tests/test_weekly_campaign_brief.py` compares the Weekly Campaign Brief's email HTML and plain text
against `tests/snapshots/`. After a deliberate change to a layout, a partial or the fixtures,
refresh them and read the diff:

```
DISPATCH_UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/test_weekly_campaign_brief.py
```

## How to send a test

From the web app: open the record in Settings, Dispatch, and press **Send test to me**. That runs
the real job with `--test-recipient <your address>`: one email, `[TEST]` in the subject, no ledger
and no change to `last_run`.

From the command line, with credentials for `advance-campaign-app`:

```
gcloud run jobs execute advance-dispatch \
  --project=advance-campaign-app --region=australia-southeast1 \
  --args=--record-id,<id>,--test-recipient,you@example.com
```

## Deploying

```
deploy/deploy.sh setup     # once: service accounts, grants, repository, job, TTL, lifecycle
deploy/deploy.sh deploy    # tests, build, tag latest, update the job, publish templates
```

Both take `--dry-run`.
