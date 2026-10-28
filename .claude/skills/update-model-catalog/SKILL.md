---
name: update-model-catalog
description: Maintain the geospatial foundation model catalog in model_metadata/. Adds records for remote sensing / Earth observation foundation models and embedding products that are missing, and updates existing records (fill null fields, new code or weights, published DOI, new versions, new benchmarks, corrections) by reading the papers and repos. Use when the user wants to update, extend, refresh, complete or fix the catalog, scan arXiv for new geo foundation models or Earth embeddings, add a specific paper or model (by name, arXiv id, DOI or URL), or improve or correct one or more existing records.
---

# Update the geo foundation model catalog

The catalog is `model_metadata/<id>.json`, one record per model, validated against
`model_schema_mlm.json` (both at the repo root). This skill does two things, often in
the same run:

- **Add**: find models that are missing, read their papers, write new records.
- **Update**: re-read the sources of existing records and improve them.

Helper scripts are in `.claude/skills/update-model-catalog/scripts/`. Run them from
the repo root; they locate the catalog themselves. `catalog.py` shorthand below means
`python .claude/skills/update-model-catalog/scripts/catalog.py`. `$TMP` means a
scratch directory outside the repo: `$CLAUDE_JOB_DIR/tmp` if set, else a fresh
`mktemp -d`.

## 1. Decide the scope

Map the request to one or both modes:

| Request | Mode |
|---|---|
| "find new models", "scan arXiv", "add <paper>" | Add (step 2) |
| "update <model>", "fix <record>", "fill in missing params" | Update (step 3) |
| "refresh / update the catalog" with no target | Both: add new models, then update the records with the most gaps |

A named model that is already catalogued is an update, not a duplicate record; a
named model that is missing is an add. Check with:

```bash
catalog.py index                                                  # id, name, arXiv/DOI, release date
catalog.py check "ModelName" 2510.12345 https://github.com/org/repo  # NEW or matching file(s)
```

`similar name` hits need a look: a new version of a catalogued model (e.g. v2 of
something whose v1 is listed) gets its own record; the same model is an update.

## 2. Add: collect and screen candidates

If the user named papers or models, those are the candidates. Otherwise gather from
several sources, since none is complete:

- **Literature search** (main source). Save the output, it takes a few minutes:
  ```bash
  python .claude/skills/update-model-catalog/scripts/search.py [--since YYYY-MM-DD] [--sources ...] > "$TMP/candidates.tsv"
  ```
  It queries arXiv, OpenAlex citations (new papers citing catalogued models),
  OpenAlex keywords (journals and conferences), Semantic Scholar, and Google Scholar,
  merges duplicates across sources, and drops papers already catalogued. Default
  `--since` is 30 days before the newest `release_date` in the catalog; use the
  user's date range if they gave one. Columns: status, sources, cites, ref, date,
  venue, title. Screen high `cites` rows and rows found by several sources first.
  The `#` lines on stderr report per-source counts and failures: if a source failed
  (Scholar captcha, OpenAlex daily budget, Semantic Scholar 429), say so in the
  report and rerun only that source later with `--sources`. An `OPENALEX_API_KEY` or
  `S2_API_KEY` in the environment raises those limits; suggest one if a source keeps
  failing.
- **Web search** (your WebSearch tool), for what the APIs index late: very recent
  model releases announced on blogs, Hugging Face or GitHub, and journal papers from
  the last few weeks, e.g. `"foundation model" remote sensing <month year>`.
- **Curated lists**, for models the keyword search misses or that predate it: GitHub
  "awesome" lists of remote sensing foundation models (e.g.
  `Jack-bo1220/Awesome-Remote-Sensing-Foundation-Models`) and benchmark leaderboards
  (PANGAEA, GEO-Bench, Copernicus-Bench) that list evaluated models.
- **Embedding products** published as datasets rather than papers (Google Earth
  Engine, Source Cooperative, Hugging Face) when the user asks for embeddings.

Run candidates from web search and curated lists through `catalog.py check`
(`search.py` output is already checked; a journal version of a catalogued arXiv
paper can still slip through, so check names that look familiar). Then read each
abstract. **Include**
papers that release or introduce a general-purpose pretrained model or embedding
product for remote sensing / EO / geospatial data: self-supervised or supervised
backbones, vision-language models, generative models, location encoders, and
precomputed embedding fields (the catalog already holds all of these kinds).
**Exclude**: evaluations or benchmarks of existing models, datasets without a model,
fine-tuning an existing model for one task, compression/distillation of task-specific
networks, surveys. A paper that evaluates a catalogued model can still feed an
update (e.g. a new version or released weights), but not a new record.

## 3. Update: pick records and what to change

If the user named records or fields, use those. Otherwise find the weakest records:

```bash
catalog.py gaps --top 20                                   # most empty fields overall
catalog.py gaps --field release_date --field mlm:total_parameters --field assets
```

Worth checking for each record being updated:

- null fields the paper, appendix or repo actually answers;
- `sci:doi` still on arXiv while the paper has since been published (journal or
  conference DOI);
- `assets`: code repo or weights released after the record was written;
- `benchmarks` missing tables from the paper, or values that do not match it;
- a newer arXiv version with changed numbers (use the latest version's numbers);
- values that contradict the paper (fix them).

## 4. Confirm the plan

When run interactively, show the user the plan before extracting: new models to add
(name, arXiv id, one-line reason), records to update (id, what you will look for), and
excluded borderline candidates. Let them adjust it. If the plan is long (>10 items),
propose doing the newest or emptiest first.

## 5. Extract

Read `references/extraction.md` before touching the first record: it holds the source
order, field conventions, id rules, and the merge rules for updates.

- **Add**: read the full paper (HTML or PDF, including the appendix), check the repo
  and weights page, write `model_metadata/<id>.json` with every schema field present.
- **Update**: first copy the record to the temp dir
  as `$TMP/<id>.orig.json`, then
  re-read the sources and edit the record in place following the merge rules. Keep
  `id` and the filename unchanged; set `updated` to today.

With more than two records, delegate: one subagent per record, in parallel. Tell each
the mode (add/update), the paper link, the target path, what to look for (for
updates), and to read `model_schema_mlm.json`,
`.claude/skills/update-model-catalog/references/extraction.md` and, for adds, one
existing record (e.g. `model_metadata/anysat.json`) as a style example. Ask each to
return the fields still null because the sources do not state them, and, for updates,
every existing value it changed with the evidence (section/table of the paper).

## 6. Validate and review

```bash
uv run --with jsonschema python .claude/skills/update-model-catalog/scripts/catalog.py validate model_metadata/<id>.json ...
catalog.py diff $TMP/<id>.orig.json model_metadata/<id>.json   # for each updated record
```

Fix every validation failure. Read each diff: any `REMOVED` line or changed non-null
value must be backed by the source; otherwise restore the original value. Spot-check
new records against their papers: name, DOI, parameter count, and two or three
benchmark numbers.

## 7. Report

- **Added**: file, model name, arXiv id, notable fields left null.
- **Updated**: file, and per field what changed (filled / corrected, with the source),
  taken from the diffs. Call out corrections of existing values separately from
  fills, since those are the ones the user should eyeball.
- **Excluded / not changed**: candidates skipped and records where the sources gave
  nothing new, with a short reason.

Do not commit unless asked.
