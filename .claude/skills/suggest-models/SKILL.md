---
name: suggest-models
description: Recommend geospatial / remote sensing foundation models or precomputed Earth embeddings from the catalog in model_metadata/ for a user's use case. Use when someone describes an application (crop monitoring, flood mapping, land cover, forest, urban, biomass, change detection...), a region, a time period, their data, labels or compute budget and asks which model, backbone or embedding to use, what would suit them, or how catalogued models compare for their task, e.g. "I'm doing crop monitoring in South Africa for 2025 and have no compute, what would you suggest?". Read-only; to add or fix records use update-model-catalog.
---

# Suggest models from the catalog

The catalog is `model_metadata/<id>.json`, one record per model or embedding product.
Recommend from these records, not from memory: every suggestion must be a catalogued
`id`, and every claim about it (size, sensors, benchmark numbers, weights) must come
from its record or from a source you checked in this run. Do not edit records here.

`recommend.py` below means
`python3 .claude/skills/suggest-models/scripts/recommend.py`, run from the repo root.

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

Run a broad query first, then tighten. Pass synonyms and region names at several
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

Then read the top 5-8 in detail, filtered to the relevant benchmarks:

```bash
recommend.py show alphaearth tessera presto --task crop --region africa
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
  embedding products need no inference at all. Released weights or a product link
  (`assets.weights`) vs code only.
- **Does it cover their period?** Embedding products exist only for the years
  published: if the record's `end_datetime` is before the requested year, check the
  product page (the `assets.weights` link) for newer layers before recommending it,
  and say what you found. For models, check that the input sensors still acquire
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
suitable, say so plainly rather than stretching a weak match; suggest running
`update-model-catalog` if a known model seems to be missing.
