---
name: find-new-models
description: Find geospatial / remote sensing / Earth observation foundation models and embedding products that are not yet in model_metadata/, read their papers, and add one schema-valid JSON record per model. Use when the user wants to update, extend or refresh the model catalog, scan arXiv for new geo foundation models or Earth embeddings, or add a specific paper or model (by name, arXiv id, DOI or URL) to model_metadata/.
---

# Find new geo foundation models

The catalog is `model_metadata/<id>.json`, one record per model, validated against
`model_schema_mlm.json` (both at the repo root). This skill finds models that are
missing, reads their papers, and writes new records. It never overwrites or edits
existing records unless the user asks.

Helper scripts live in this skill's `scripts/` directory (`.claude/skills/find-new-models/scripts/`). Run them
from the repo root; they locate the catalog themselves.

## 1. Know what is already there

```bash
python .claude/skills/find-new-models/scripts/catalog.py index        # id, name, arXiv/DOI, release date
```

## 2. Collect candidates

If the user named specific papers or models, those are the candidates; skip to step 3.

Otherwise gather candidates from several sources, since none is complete:

- **arXiv** (main source):
  `python .claude/skills/find-new-models/scripts/search_arxiv.py [--since YYYY-MM-DD] [--max 300]`
  prints uncatalogued papers since 30 days before the newest `release_date` in the
  catalog. Use the user's date range if they gave one.
- **Curated lists**, for models the keyword search misses or that predate it: GitHub
  "awesome" lists of remote sensing foundation models (e.g.
  `Jack-bo1220/Awesome-Remote-Sensing-Foundation-Models`) and benchmark leaderboards
  (PANGAEA, GEO-Bench, Copernicus-Bench) that list evaluated models.
- **Embedding products** published as datasets rather than papers (e.g. on Google
  Earth Engine, Source Cooperative, Hugging Face) when the user asks for embeddings.

Check every candidate (name, arXiv id, repo URL) against the catalog:

```bash
python .claude/skills/find-new-models/scripts/catalog.py check "ModelName" 2510.12345 https://github.com/org/repo
```

`similar name` hits need a look: it may be a new version (gets its own record) or the
same model.

## 3. Screen

Read the abstract of each candidate. **Include** papers that release or introduce a
general-purpose pretrained model or embedding product for remote sensing / EO /
geospatial data: self-supervised or supervised backbones, vision-language models,
generative models, location encoders, and precomputed embedding fields (the catalog
already holds all of these kinds). **Exclude**: evaluations or benchmarks of existing
models, datasets without a model, fine-tuning an existing model for one task,
compression/distillation of task-specific networks, surveys.

When run interactively, show the user the shortlist (name, arXiv id, one-line reason)
and the excluded borderline cases before extracting, and let them adjust it. If the
shortlist is long (>10), propose doing the newest/most relevant first.

## 4. Extract one record per model

Read `references/extraction.md` before writing the first record; it holds the source
order, field conventions and id rules. Then for each model: read the full paper
(HTML or PDF, including the appendix), check the repo/weights page, and write
`model_metadata/<id>.json`.

With more than two models, delegate: one subagent per paper, in parallel, each told
the paper link, the target path, and to read `model_schema_mlm.json`,
`.claude/skills/find-new-models/references/extraction.md` and one existing record (e.g.
`model_metadata/anysat.json`) as a style example, and to return the fields it left
null because the paper did not state them.

## 5. Validate

```bash
uv run --with jsonschema python .claude/skills/find-new-models/scripts/catalog.py validate model_metadata/<id>.json ...
```

Fix every failure. Then spot-check each new record against its paper: name, DOI,
parameter count, and two or three benchmark numbers.

## 6. Report

List per new record: file, model name, arXiv id, and notable gaps (important fields
left null). List the candidates you excluded with a short reason, so the user can
override. Do not commit unless asked.
