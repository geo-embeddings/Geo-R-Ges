"""Validate catalog records against the schemas plus checks JSON Schema can't express.

    uv run --with jsonschema python scripts/validate.py            # every record in database/
    uv run --with jsonschema python scripts/validate.py FILE ..    # only these records

A file is checked against the model or embedding schema by its folder (models/ or
embeddings/). Cross-record checks (duplicate ids, encoder_model.id) always use the
whole catalog.
"""

import json
import sys
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

from recommend import DB, SCHEMAS, SKILL_DIR, record_files


def load_validators():
    schemas = {p.name: json.loads(p.read_text()) for p in (SKILL_DIR / "schema").glob("*.json")}
    registry = Registry().with_resources(
        [(n, Resource.from_contents(s)) for n, s in schemas.items()]
        + [(s["$id"], Resource.from_contents(s)) for s in schemas.values()]
    )
    return {sub: jsonschema.Draft202012Validator(schemas[path.name], registry=registry,
                                                 format_checker=jsonschema.FormatChecker())
            for sub, path in SCHEMAS.items()}


def check_benchmarks(rec):
    for i, b in enumerate(rec.get("benchmarks") or []):
        m, v = b.get("metrics") or [], b.get("metrics_value") or []
        if len(m) != len(v):
            yield f"benchmarks[{i}] ({b.get('dataset')}): {len(m)} metrics vs {len(v)} values"


def check_product_assets(rec):
    # Embeddings extension: at least one asset with the role 'embeddings'.
    if not any("embeddings" in (a.get("roles") or []) for a in (rec.get("assets") or {}).values()):
        yield "no asset with role 'embeddings'"


def main():
    validators = load_validators()
    every = list(record_files(DB))
    wanted = {Path(p).resolve() for p in sys.argv[1:]}
    errors, ids, model_ids, records = [], {}, set(), []
    for sub, path in every:
        try:
            rec = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}: invalid JSON ({e})")
            continue
        records.append((sub, path, rec))
        if rec.get("id") in ids:
            errors.append(f"{sub}/{path.name}: duplicate id, also in {ids[rec['id']]}")
        ids[rec.get("id")] = f"{sub}/{path.name}"
        if sub == "models":
            model_ids.add(rec.get("id"))

    for path in wanted - {p.resolve() for _, p in every}:
        errors.append(f"{path}: not inside {DB}/models or {DB}/embeddings")

    checked = 0
    for sub, path, rec in records:
        if wanted and path.resolve() not in wanted:
            continue
        checked += 1
        rel = f"{sub}/{path.name}"
        for e in validators[sub].iter_errors(rec):
            errors.append(f"{rel}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
        if path.stem != rec.get("id"):
            errors.append(f"{rel}: filename does not match id '{rec.get('id')}'")
        errors += [f"{rel}: {msg}" for msg in check_benchmarks(rec)]
        if sub == "embeddings":
            errors += [f"{rel}: {msg}" for msg in check_product_assets(rec)]
            enc = rec.get("encoder_model") or {}
            if enc.get("id") and enc["id"] not in model_ids:
                errors.append(f"{rel}: encoder_model.id '{enc['id']}' has no model record")

    for e in errors:
        print(e)
    n_models = sum(1 for sub, _ in every if sub == "models")
    print(f"{checked} records checked ({n_models} models, {len(every) - n_models} embedding products in catalog), "
          f"{len(errors)} errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
