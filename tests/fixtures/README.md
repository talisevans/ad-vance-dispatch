# Test fixtures

A small gold and lookup parquet set with values chosen so every figure can be checked by hand.
Rebuild it with:

```
.venv/bin/python tests/fixtures/build_fixtures.py
```

Layout (the same as the API's local mirror):

```
gold/<table>/year=<YYYY>/part-0.parquet    ad_daily, adverts, ad_geo, ad_state, ad_demo, ad_platform
gold/electorates/part-0.parquet
lookups/affiliations/part-0.parquet
lookups/bias_definitions/part-0.parquet
lookups/content_creators/part-0.parquet
```

Open it with `LocalGoldSource(gold_dir, lookups_dir)` and `open_gold_from`, or use the
`gold_connection` and `reference` pytest fixtures in `tests/conftest.py`.

Every total below is asserted in `tests/test_fixture_totals.py`, so this file and the data cannot
drift apart silently. The section tests (`tests/test_section_*.py`) assert the same figures through
each section's own output, plus the per-section figures in "Section figures" at the end.

## Dates

| | |
|---|---|
| Meta's latest date (`as_of`) | 2026-10-01 |
| Google's latest date | 2026-10-02 (one day after Meta, the "partial day") |
| 7-day window | 2026-09-25 to 2026-10-01 |
| 28-day window | 2026-09-04 to 2026-10-01 |
| Sample `start_date` (cumulative anchor) | 2026-08-01 |
| Sample `end_date` | 2026-11-28 (after `as_of`, so windows end on `as_of`) |

Google does reach the window end, so the Google callout does **not** appear on the fixtures.
`tests/test_as_of.py` builds its own tiny tables for the callout cases.

## Rules of the data

- Every advert spends a whole number of dollars every day from its first to its last date,
  inclusive. Impressions are 10 per dollar.
- Every weight is a round share and each advert's weights sum to 1.
- Government creators carry a null `creator_affiliation_bias` in gold, as the ETL writes it.
- `meta_V12` starts in 2025, so it sits in the `year=2025` partition.

## Reference data

Biases (positions and colours as live): extreme left -2 `#991b1b`, left -1 `#ef4444`,
centrist 0 `#94a3b8`, right 1 `#3b82f6`, extreme right 2 `#1e40af`. `bias_slots()` puts
`unmapped` straight after `centrist`.

| Affiliation id | Name | Bias | Stored colour | Notes |
|---|---|---|---|---|
| aff_labor | Labor | left | none (party red `#dc2626`) | |
| aff_liberal | Liberal | right | none (party blue `#1e3a8a`) | |
| aff_lib_old | Liberal Party (Victorian Division) | right | none | **superseded by aff_liberal** |
| aff_greens | Greens | left | none (party green `#22c55e`) | a stale June row named "Australian Greens (stale row)" must be hidden |
| aff_climate_200 | Climate 200 | centrist | `#0F766E` (read as `#0f766e`) | |
| aff_one_nation | One Nation | extreme right | none | NSW only |
| aff_ipa | Institute of Public Affairs | right | none (fallback slot `#2563eb`) | interest group |
| aff_vic_government | Victorian Government | null | none | government |
| aff_fed_government | Australian Government | null | none | government |
| aff_socialist_alliance | Socialist Alliance | extreme left | none | **no adverts at all**: use it for a zero-spend card |

Creators with no affiliation (unmapped): `c_jane_smith` (Jane Smith for Kew, political participant),
`c_bob_lee` (Bob Lee Independent, political participant), `c_concerned` (Concerned Citizens of
Brunswick, interest group), `c_fair_go` (Fair Go Alliance, federal interest group).

Seats: state VIC `state_20001` Kew, `state_20002` Hawthorn, `state_20003` Brunswick; state NSW
`state_10078` Sydney, `state_10084` Vaucluse; federal VIC `federal_225` Kooyong, `federal_232`
Melbourne; federal NSW `federal_144` Wentworth, `federal_141` Sydney.

## Adverts

| Ad key | Source | Creator | Juris. | $/day | First to last | Tone | Themes | States | Seats |
|---|---|---|---|---|---|---|---|---|---|
| meta_V01 | meta | c_labor_vic | state | 100 | 08-01 to 10-01 | positive | Health, Cost of Living | VIC 1 | Kew .5, Hawthorn .3, Brunswick .2 |
| meta_V02 | meta | c_liberal_vic | state | 80 | 08-01 to 10-01 | negative | Cost of Living, Crime | VIC 1 | Kew .5, Hawthorn .5 |
| meta_V03 | meta | c_liberal_old (aff_lib_old) | state | 20 | 09-01 to 10-01 | compare & contrast | Crime | VIC 1 | Kew 1 |
| meta_V04 | meta | c_greens_vic | state | 50 | 09-15 to 10-01 | positive | Climate | VIC 1 | Brunswick 1 |
| meta_V05 | meta | c_teal_kew (Climate 200) | state | 150 | 09-20 to 10-01 | **null** | Climate, Integrity | VIC 1 | Kew 1 |
| meta_V06 | meta | c_jane_smith (unmapped) | state | 30 | 09-25 to 10-01 | positive | Local Roads | VIC 1 | Kew 1 |
| meta_V07 | meta | c_bob_lee (unmapped) | state | 30 | 09-25 to 10-01 | negative | **none** | VIC 1 | Kew 1 |
| meta_V08 | meta | c_vic_gov (government) | state | 200 | 08-01 to 10-01 | positive | Health | VIC 1 | Kew .4, Hawthorn .3, Brunswick .3 |
| meta_V09 | meta | c_ipa (interest group) | state | 40 | 09-01 to 10-01 | negative | Energy, Cost of Living | VIC 1 | Hawthorn 1 |
| google_V10 | google | c_concerned (unmapped) | state | 25 | 09-10 to 10-02 | **null** | Housing | VIC 1 | Brunswick 1 |
| google_V11 | google | c_labor_vic | state | 60 | 09-01 to 10-02 | positive | Health | VIC 1 | Kew .5, Brunswick .5 |
| meta_V12 | meta | c_labor_vic | state | 10 | 2025-12-01 to 08-31 | positive | Health | VIC 1 | Hawthorn 1 |
| meta_V13 | meta | c_concerned (unmapped) | state | 10 | 09-25 to 10-01 | positive | Local Roads | VIC 1 | Brunswick 1 (local government content) |
| meta_N01 | meta | c_labor_nsw | state | 70 | 08-15 to 10-01 | positive | Housing | NSW 1 | Sydney .6, Vaucluse .4 |
| meta_N02 | meta | c_liberal_nsw | state | 90 | 08-15 to 10-01 | negative | Housing, Crime | NSW 1 | Vaucluse 1 |
| meta_N03 | meta | c_one_nation_nsw | state | 15 | 09-01 to 10-01 | negative | Immigration | NSW 1 | Sydney 1 |
| meta_F01 | meta | c_labor_fed | federal | 300 | 08-01 to 10-01 | positive | Cost of Living | VIC .4, NSW .6 | Kooyong .2, Melbourne .2, Wentworth .3, Sydney .3 |
| google_F02 | google | c_liberal_fed | federal | 120 | 09-01 to 10-02 | negative | Cost of Living, Defence | VIC .5, NSW .5 | Kooyong .5, Wentworth .5 |
| meta_F03 | meta | c_fed_gov (government) | federal | 500 | 08-01 to 10-01 | positive | Health | VIC .5, NSW .5 | each federal seat .25 |
| meta_F04 | meta | c_greens_fed | federal | 40 | 09-25 to 10-01 | positive | Climate | VIC 1 | Melbourne 1 |
| meta_F05 | meta | c_fair_go (unmapped) | federal | 20 | 09-01 to 10-01 | compare & contrast | Cost of Living | NSW 1 | Wentworth 1 |

All dates are 2026 unless written in full.

## Key totals

"No government" means the Weekly Campaign Brief's global filter, `exclude classification
[government]`. Bias groups use `coalesce(creator_affiliation_bias, 'unmapped')`.

### Victorian state record (jurisdiction `state`, state `VIC`), statewide (`ad_state_daily`)

| Figure | 7 days | 28 days |
|---|---|---|
| All spend | $5,565 | $17,690 |
| No government | $4,165 | $12,090 |
| left (no government) | $1,470 | $5,330 |
| centrist | $1,050 | $1,800 |
| unmapped | $665 | $1,040 |
| right | $980 | $3,920 |

Gauge headline (7 days): Left $1,470, Centre and unmapped $1,715, Right $980, total $4,165.

Worked check, 7-day left: Labor `meta_V01` 7 x $100 = $700, Labor `google_V11` 7 x $60 = $420,
Greens `meta_V04` 7 x $50 = $350. Total $1,470.

### Cumulative, 2026-08-01 to 2026-10-01, no government, by affiliation id as gold holds it

| Affiliation | Total | Merged view |
|---|---|---|
| aff_labor | $8,370 | Labor $8,370 |
| aff_liberal | $4,960 | Liberal $5,580 (with aff_lib_old) |
| aff_climate_200 | $1,800 | |
| aff_ipa | $1,240 | |
| null (unmapped) | $1,040 | Unmapped $1,040 |
| aff_greens | $850 | |
| aff_lib_old | $620 | folds into Liberal |

By bias over the same range: left $9,220, right $6,820, centrist $1,800, unmapped $1,040.

With `top_affiliations: 3` and merges resolved: Labor $8,370, Liberal $5,580, Climate 200 $1,800,
Other (IPA + Greens) $2,090, Unmapped $1,040. Without merges, Liberal is $4,960 and Other is
$2,710.

Spend per ISO week (Monday start, no government): week of 27 Jul (1 to 2 Aug only) $380; 3 Aug,
10 Aug, 17 Aug, 24 Aug $1,330 each; 31 Aug $1,990; 7 Sep $2,200; 14 Sep $2,725; 21 Sep $3,885;
28 Sep (28 Sep to 1 Oct only) $2,380.

### Messaging, 28 days, no government

Spend by affiliation and tone:

| Affiliation | Tone | Spend |
|---|---|---|
| aff_labor | positive | $4,480 |
| aff_liberal | negative | $2,240 |
| aff_lib_old | compare & contrast | $560 |
| aff_greens | positive | $850 |
| aff_climate_200 | null (Unclassified) | $1,800 |
| aff_ipa | negative | $1,120 |
| unmapped | null / negative / positive | $550 / $210 / $280 |
| aff_socialist_alliance | none | $0 (zero-spend card) |

A Liberal card with `affiliation_ids: ["aff_liberal"]` matches both ids through the merge: $2,800,
80% negative, 20% compare and contrast.

Themes (each counted in full for every advert carrying it, so they overlap): Cost of Living
$6,160, Health $4,480, Crime $2,800, Climate $2,650, Integrity $1,800, Energy $1,120, Housing $550,
Local Roads $280.

### Top Seats, VIC state, political participants only, by `ad_geo_daily`

| Seat | Spender key | 7 days | 28 days |
|---|---|---|---|
| Kew | aff_climate_200 | $1,050 | $1,800 |
| Kew | aff_labor | $560 | $2,240 |
| Kew | aff_liberal | $280 | $1,120 |
| Kew | aff_lib_old | $140 | $560 |
| Kew | creator:c_jane_smith | $210 | $210 |
| Kew | creator:c_bob_lee | $210 | $210 |
| Brunswick | aff_greens | $350 | $850 |
| Brunswick | aff_labor | $350 | $1,400 |
| Hawthorn | aff_liberal | $280 | $1,120 |
| Hawthorn | aff_labor | $210 | $840 |

Seat totals: Kew $2,450 (7 days) and $6,140 (28 days); Brunswick $700 and $2,250; Hawthorn $490
and $1,960. Seats rank Kew, Brunswick, Hawthorn.

Cases worth a test:

- **Leader tie**: Brunswick 7 days is Greens $350 against Labor $350. Ties break on spender key,
  so `aff_greens` leads and `aff_labor` is runner-up.
- **Unmapped independents not merged**: Jane Smith and Bob Lee are separate spenders at $210
  each, ordered `creator:c_bob_lee` before `creator:c_jane_smith`.
- **Merged affiliation**: with merges resolved, Kew's Liberal is $420 over 7 days ($280 + $140)
  and $1,680 over 28 days. Kew's leader is Climate 200 ($1,050) and runner-up Labor ($560) either
  way; the merge changes the Liberal figure, not the order.

### New South Wales state record

No government: 7 days $1,225, 28 days $4,900.

### Federal records (national, `ad_daily`)

7 days, all spend: $6,860 (left $2,380, right $840, government $3,500, unmapped interest group
$140). Federal with state VIC (`ad_state_daily`): $3,290 (left $1,120, right $420, government
$1,750).

## Section figures

Worked from the advert table above, asserted in `tests/test_section_*.py`.

- **Bias gauge, federal national, 7 days, government dropped**: $6,860 less $3,500 government is
  $3,360. Left $2,380, Centre and unmapped $140 (Fair Go Alliance), Right $840.
- **Bias gauge with no template filter at all**: still $4,165 for VIC over 7 days. Government's
  $1,400 has a null bias in gold, so without the section's own drop unmapped would read $2,065.
- **Messaging cards, VIC, 28 days** (4 September to 1 October):
  - Labor $4,480. `meta_V01` 28 x $100 = $2,800 (Health, Cost of Living) and `google_V11`
    28 x $60 = $1,680 (Health). Themes: Health $4,480, Cost of Living $2,800 (bar 62.5%, drawn
    63%). Tone 100% positive.
  - Liberal $2,800 (with `aff_lib_old`). Themes: Crime $2,800, Cost of Living $2,240 (bar 80%).
  - Teals (Climate 200) $1,800, 100% Unclassified. Climate and Integrity tie at $1,800, ordered by
    name.
  - Greens $850. Socialist Alliance $0: the card is kept, last and greyed.
- **Top Seats, federal VIC record**: only Kooyong and Melbourne appear.
- **Top Seats, unmapped independents**: narrowed to `c_jane_smith` and `c_bob_lee`, Kew's leader
  is Bob Lee Independent $210 (key `creator:c_bob_lee`) and runner-up Jane Smith for Kew $210.
- **Top Seats, Liberal only**: Kew's leader is Liberal $420 (7 days) and $1,680 (28 days), with
  runner-up "none".
