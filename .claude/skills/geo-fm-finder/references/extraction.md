# Extracting one model record from a paper

The schema (`model_schema_mlm.json` at the repo root) is the source of truth: read
its field descriptions before writing a record. This file adds the conventions the
existing records in `model_metadata/` follow, the rules for updating an existing
record, and the mistakes to avoid.

## Sources, in order of preference

1. **The paper full text.** For arXiv, fetch `https://arxiv.org/html/<id>` (HTML,
   tables preserved). If there is no HTML version, download
   `https://arxiv.org/pdf/<id>` into `$CLAUDE_JOB_DIR/tmp` (or a temp dir) and extract
   text (`pdftotext -layout`, or `uv run --with pypdf`). The abstract alone is never
   enough: hyperparameters, datasets and benchmark tables live in the method,
   experiments and appendix sections. Read the appendix.
2. **The code repository** (link usually in the abstract or first page): README,
   config files for patch size / epochs / batch size / learning rate, model cards.
3. **Released weights** (Hugging Face, Zenodo, GEE catalog): link and parameter count.

Record only what these sources state. When something is not stated, write `null`.
Do not fill in values from general knowledge of similar models.

## Field conventions

- `id`: lowercase slug of the model name, hyphens only (`Prithvi-EO-2.0` ->
  `prithvi-eo-2-0`, `AlphaEarth Foundations` -> `alphaearth`). Filename is
  `model_metadata/<id>.json`. If the id already exists for a *different* model, append
  a disambiguator such as the first author or venue/year (`galileo-icml2025`).
- `mlm:name`: family name as the authors write it, no size suffix.
- `version`: only if the authors name one (`v1`, `2.0`); new versions of a catalogued
  model get their own record with their own id.
- `release_date`: first public release, normally the arXiv v1 submission date, as
  `YYYY-MM-DDT00:00:00Z`. `updated`: today's date in the same format.
- `description`: 2-4 sentences in your own words: what it is, inputs, how trained,
  what it is good at.
- `sci:doi`: arXiv papers -> `10.48550/arXiv.<id>` (no version suffix). Prefer the
  journal/conference DOI when the paper has been published and the DOI is printed.
- `assets`: `mlm:source_code` for the repo (`type: text/html`, roles
  `["mlm:source_code", "code"]`); `weights` for released weights (roles
  `["mlm:model", "mlm:weights"]`). Only links you actually saw; omit the key otherwise.
- `mlm:architecture`: generic name first, then variants:
  `Vision Transformer (ViT-S, ViT-B, ViT-L)`.
- `mlm:total_parameters`: raw integer of the largest released variant (300M ->
  300000000). Null if not stated anywhere.
- `modality_integration_type`, `spectral_alignment`, `temporal_alignment`: enums; use
  the definitions in the schema. These are judgements, so decide from what the
  architecture does, not from marketing language.
- `mlm:input`: one entry per sensor where the paper lists bands per sensor. Use band
  names as the paper does (`B2`, `VV`). Add `input.shape` + `dim_order` only when the
  pretraining tile size and band count are both stated (`[-1, 12, 96, 96]`,
  `["batch", "bands", "height", "width"]`).
- `start_datetime` / `end_datetime`: acquisition period of the pretraining data.
  Year-only statements -> `YYYY-01-01T00:00:00Z` / `YYYY-12-31T23:59:59Z`.
- `num_images`: integer count of pretraining samples, before augmentation.
- `mlm:hyperparameters`: `mask_ratio` as a fraction (75% -> 0.75); `batch_size` is the
  global batch; `learning_rate` is a string including schedule. Extra keys allowed
  (e.g. `num_layers`, `embedding_dim`) when clearly stated.
- `benchmarks`: one entry per (dataset, task) from the paper's own results tables,
  for the paper's model only (not baselines). Use the largest/best variant, or the
  main row the authors highlight. `metrics` names include the protocol and label
  fraction when the paper reports several (`mIoU (linear probe)`,
  `Top-1 Acc (kNN, 1% train)`); `metrics_value` is parallel, numbers as reported
  (usually percent). Use the GEO-Bench / PANGAEA dataset naming the paper uses
  (`m-EuroSat (GEO-Bench)`).

## Updating an existing record

Existing records were partly written by other tools and people. Improve them without
losing information:

- **Fill** a null/empty field when the sources state the value.
- **Keep** a non-null value unless the source contradicts it. Different wording of
  the same fact is not a contradiction; leave free-text fields alone unless they are
  wrong or much less informative than the paper.
- **Correct** a value only with evidence (paper section/table, repo file, model card)
  and note that evidence in your report. Never set a non-null value back to null just
  because you could not find it.
- **Lists** (`supported_sensors`, `modalities`, `domain_knowledge`, ...): add missing
  items; remove an item only if it is clearly wrong for this model.
- **`benchmarks`**: match entries on (dataset, task). Fix values that differ from the
  paper, add missing ones, and keep entries you cannot find (they may come from
  another version or table) unless they are clearly not this model's results.
- **`assets`**: add new repos or weights; replace a dead link only when you found the
  new location.
- **`sci:doi`**: replace an arXiv DOI with the published venue DOI once you have
  confirmed it on the publisher or DOI page.
- **Unchanged identity**: never change `id` or rename the file. Set `updated` to
  today (`YYYY-MM-DDT00:00:00Z`); leave `release_date` unless it is null or wrong.
- Add any schema fields the record is missing as `null` (or the found value), so it
  matches the full schema shape.

## Before saving

- Every key in the schema's `properties` should be present (use `null`), matching the
  shape of existing records, so records stay uniform.
- Numbers are numbers, not strings; enums are exact (`"Heterogeneous Multimodal"`).
- Re-read the description and benchmark values against the paper once.
