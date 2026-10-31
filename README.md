# Geo Foundation Finder

A skill and a dataset to help discover geospatial foundation models and embedding datasets.

## Install the skill

`geo-fm-finder` follows the [Agent Skills](https://agentskills.io) format, so it works with
Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode and other compatible agents.

### Any agent

Any agent via the [`skills` CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add geo-embeddings/Geo-R-Ges        # pick agents interactively
npx skills add geo-embeddings/Geo-R-Ges -g     # install globally instead of per project
npx skills update                              # pull catalog updates later
```

### Claude Code

**Claude Code** (as a plugin):

```
/plugin install geo-fm-finder --marketplace geo-embeddings/Geo-R-Ges
```

### Manual

**Manual**: clone the repo and copy or symlink `skills/geo-fm-finder` into your agent's skills
directory, e.g. `ln -s "$PWD/skills/geo-fm-finder" ~/.claude/skills/geo-fm-finder` (Claude Code)
or `~/.agents/skills/geo-fm-finder` (Codex and other agents reading `.agents/skills`).

## Layout

- `skills/geo-fm-finder/`: the distributable `geo-fm-finder` skill, self-contained:
  - `SKILL.md`, `references/`: instructions for the recommend and update modes
  - `schema/`: JSON Schemas for model records (STAC MLM field names) and embedding product records (STAC Embeddings extension field names)
  - `database/models/`, `database/embeddings/`: one JSON record per model / embedding product; `database/INDEX.md` is generated
  - `scripts/`: `recommend.py`, `catalog.py`, `validate.py`, `search.py`; they find the catalog relative to themselves, so they run from any directory
- `.claude-plugin/marketplace.json`: Claude Code plugin marketplace entry
- `scripts/`: maintainer tools not shipped with the skill (REMSA importers)

## Maintain the catalog

```bash
uv run --with jsonschema python skills/geo-fm-finder/scripts/validate.py  # schemas + cross-record checks
python skills/geo-fm-finder/scripts/catalog.py write-index  # regenerate database/INDEX.md
```
