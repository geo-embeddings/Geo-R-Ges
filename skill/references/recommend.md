# Recommend mode: suggest models from the catalog

The catalog is `<skill>/database/`: `models/<id>.json`, one record per model, and
`embeddings/<id>.json`, one record per precomputed embedding product.
Recommend from these records, not from memory: every suggestion must be a catalogued
`id`, and every claim about it (size, sensors, benchmark numbers, weights) must come
from its record or from a source you checked in this run. Do not edit records in this
mode; catalog changes go through the handoff in `SKILL.md`.

`recommend.py` below means `python3 <skill>/scripts/recommend.py` (any working
directory).

## 1. Turn the request into constraints

Extract what the user said, and infer the rest from the use case:

| Constraint | Ask yourself | Flag |
|---|---|---|
| Task | classification, segmentation, regression, change, retrieval/VQA? pixel, parcel or scene level? | `--task` (several synonyms) |
| Region | country, plus its continent / biome, plus benchmark datasets from there | `--region` |
| Period | which year(s) must the data cover? | `--year` |
| Compute | none / laptop CPU / one GPU / cluster | `--max-params`, `--embeddings-only` |
| Data | sensor (Sentinel-2, Landsat, SAR, VHR), resolution, single date vs time series | `--sensor`, `--modality` |
| Labels | many, few, none (zero-shot)? | judgement in step 3 |
| Ready to use | needs released weights? | `--needs-weights` |

Map compute with `references/selection.md` (tiers, field-size → resolution, season
pitfalls). Only ask a clarifying question when a missing constraint would change the
top recommendation and cannot be sensibly assumed (e.g. no task given at all). Otherwise
state the assumption and continue.

## 2. Shortlist

Read `<skill>/database/INDEX.md` first: one table of models (kind, size, inputs,
resolution, time coverage, region, code / weights linked) and one of embedding
products (encoder, pixel or chip, dims, sensors, spacing, period, years, license,
hosting). It is the
quickest overview of the whole catalog and catches candidates the keyword scoring
below misses because their records word things differently. Note the plausible ids.

Then run a broad query, and tighten. Pass synonyms and region names at several
scales, since records use free text (`"crop"`, `"agricultur"`, `"field"`; `"south
africa"`, `"SA-crop"`, `"africa"`):

```bash
recommend.py candidates --task crop --task agricultur --region "south africa" \
  --region SA-crop --region africa --sensor sentinel-2 --max-params 30M --year 2025
recommend.py candidates --embeddings-only --task crop --region africa --year 2025
```

Scores are a ranking aid, not a verdict: `+` lines are the evidence, `!` lines are the
gaps and risks. `size unknown` and `no weights listed` often mean the record is
incomplete, not that the model is unsuitable.

Merge the top `candidates` with the ids you noted from the index, then read the top
5-8 in detail, filtered to the relevant benchmarks:

```bash
recommend.py show google-satellite-embedding-v1 tessera-v1-1 presto-togo-embeddings presto \
  --task crop --region africa      # products and models mix; a product card names its encoder
recommend.py leaderboard SA-crop          # every catalogued result on one dataset
```

Leaderboard numbers come from each model's own paper: different splits, label
fractions and frozen vs fine-tuned protocols. Compare across models only when
`split_ratio` and the setup match; an outlier (e.g. one model 50 points above the rest)
usually means a different protocol or metric, so say so instead of ranking on it.

## 3. Judge fit

For each candidate, check against the constraints, using the record plus
`references/selection.md`:

- **Can the user run it?** Compute tier vs `mlm:total_parameters`; precomputed
  embedding products need no inference at all. Released weights (`assets.weights`)
  vs code only. For a product: `hosting` and `access_requirements` (e.g. an Earth
  Engine account), `license`, and download size vs `spatial_resolution` (10 m pixel
  products are large for big areas; chip products are small).
- **Does the product's shape fit the task?** `emb:type` pixel (per-pixel maps, field
  boundaries) vs chip (scene/patch retrieval, coarse mapping), and the spacing
  between vectors vs the object size. `show` lists the products a model feeds and
  the model behind a product (`encoder_model`): use the model's benchmarks as
  evidence for its product, and say that you did.
- **Does it cover their period?** Embedding products exist only for the years
  published: if the record's `end_datetime` is before the requested year, or is null
  (ongoing product), read `temporal_coverage_note` and check the product page (the
  asset with role `embeddings`) for the requested layer before recommending it, and
  say what you found. For models, check that the input sensors still acquire
  data in that period.
- **Does it match their data and task?** Sensors, resolution vs object/field size,
  time series vs single date, pixel vs patch outputs.
- **Evidence for this task and region:** benchmarks on the same task, ideally in the
  same region or a similar one (same continent, climate, farming system).

Prefer a small number of well-justified options over a long list. Typically suggest
one "start here" option plus one or two alternatives for when an assumption is wrong
(e.g. "if you get a GPU" or "if you need the 2025 season before the 2025 layer ships").

## 4. Answer

Lead with the recommendation, then for each suggested model:

- **What it is and why it fits** (one or two lines, citing the record evidence:
  benchmark + dataset + value, size, sensors).
- **How to start**: the concrete path (e.g. "export annual embeddings for your AOI from
  the Earth Engine collection, train a random forest / logistic regression on your
  field labels"), with the `assets` link.
- **Watch out for**: the `!` flags that matter and use-case pitfalls from
  `references/selection.md`.

Close with what the catalog could not answer (null fields, unverified currency, no
regional benchmark) so the user knows what to check. If the catalog has nothing
suitable, say so plainly rather than stretching a weak match. If a known model seems to
be missing or the shortlist is held back by empty fields, offer the catalog update
described under "Handoff" in `SKILL.md`.
