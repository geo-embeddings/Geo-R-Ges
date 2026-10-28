# Geo Foundation Finder

A skill and a dataset to help discover geospatial foundation models and embedding datasets.

## Layout

- `skill/`: the distributable `geo-fm-finder` skill, self-contained:
  - `SKILL.md`, `references/`: instructions for the recommend and update modes
  - `schema/`: JSON Schemas for model records (STAC MLM field names) and embedding product records (STAC Embeddings extension field names)
  - `database/models/`, `database/embeddings/`: one JSON record per model / embedding product; `database/INDEX.md` is generated
  - `scripts/`: `recommend.py`, `catalog.py`, `validate.py`, `search.py`; they find the catalog relative to themselves, so they run from any directory
- `scripts/`: maintainer tools not shipped with the skill (REMSA importers)

## Use the skill

Copy or symlink `skill/` into a skills directory under the skill's name, e.g.
`ln -s "$PWD/skill" ~/.claude/skills/geo-fm-finder` (or `.claude/skills/geo-fm-finder` in a project).

## Maintain the catalog

```bash
uv run --with jsonschema python skill/scripts/validate.py   # schemas + cross-record checks
python skill/scripts/catalog.py write-index                 # regenerate skill/database/INDEX.md
```

## TODO
1. Decide json schema
2. Skill to scans for new papers and extracts metadata and creates model_information.json file per model
3. Merge in models from other metadata repos
4. Skill to help a person find a model that might work for them
