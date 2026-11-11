"""Inspect the catalog in database/ (models/ and embeddings/).

Usage:
  python catalog.py index                  # one line per record: id, name, arXiv/DOI, release date
  python catalog.py check QUERY [QUERY..]  # is a model or product (name, arXiv id, DOI or URL) already catalogued?
  python catalog.py gaps [--field F ..] [--top N] [--kind models|embeddings]  # records with the most null/missing fields
  python catalog.py diff OLD.json NEW.json # field-by-field changes between two versions of a record
  python catalog.py write-index            # regenerate database/INDEX.md (run after adding/updating records)

Validation lives in validate.py. Options: --db DIR (catalog directory holding
models/ and embeddings/; default: the skill's own database/).
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

from recommend import DB, SCHEMAS, fmt_count, is_product, kind, load_files, name, record_files


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def arxiv_id(s):
    m = re.search(r"(\d{4}\.\d{4,5})", s or "")
    return m.group(1) if m else None


load = load_files


def cmd_index(db, _):
    for _f, r in load(db):
        doi = r.get("sci:doi") or ""
        ref = f"arXiv:{arxiv_id(doi)}" if "arxiv" in doi.lower() else (doi or "-")
        date = "embedding-product" if is_product(r) else (r.get("release_date") or "-")[:10]
        print(f"{r.get('id')}\t{name(r)}\t{ref}\t{date}")


def matches(query, recs):
    """Return [(filename, reason)] for records that look like the queried model or product."""
    q_arx, q_norm = arxiv_id(query), norm(query)
    q_doi = query.lower().removeprefix("https://doi.org/")
    q_url = query.lower().rstrip("/") if query.startswith("http") else None
    hits = []
    for f, r in recs:
        doi = (r.get("sci:doi") or "").lower()
        names = [norm(name(r)), norm(r.get("id"))]
        urls = " ".join(a.get("href", "") for a in (r.get("assets") or {}).values()).lower()
        if q_arx and (q_arx == arxiv_id(doi) or q_arx in urls):
            hits.append((f.name, "arXiv id"))
        elif doi and q_doi == doi:
            hits.append((f.name, "DOI"))
        elif q_url and q_url in urls:
            hits.append((f.name, "URL"))
        elif q_norm and q_norm in names:
            hits.append((f.name, "exact name"))
        elif len(q_norm) >= 5 and not q_url and any(q_norm in n for n in names):
            hits.append((f.name, "name contains query"))
        elif q_norm and not q_url and max(difflib.SequenceMatcher(None, q_norm, n).ratio() for n in names) >= 0.85:
            hits.append((f.name, "similar name"))
    return hits


def cmd_check(db, args):
    recs = load(db)
    for q in args.queries:
        hits = matches(q, recs)
        print(f"{q}: " + ("; ".join(f"{n} ({why})" for n, why in hits) if hits else "NEW"))


def is_empty(v):
    return v is None or v == [] or v == {}


def cmd_gaps(db, args):
    """Rank records by how many schema fields are null or missing."""
    props = {sub: list(json.loads(path.read_text())["properties"]) for sub, path in SCHEMAS.items()}
    known = set().union(*props.values())
    unknown = set(args.field or []) - known
    if unknown:
        sys.exit(f"unknown field(s): {', '.join(sorted(unknown))}")
    rows = []
    for sub, f in record_files(db):
        if args.kind and sub != args.kind:
            continue
        fields = [k for k in args.field if k in props[sub]] if args.field else props[sub]
        r = json.loads(f.read_text())
        missing = [k for k in fields if is_empty(r.get(k))]
        if missing:
            rows.append((len(missing), r.get("id") or f.stem, len(fields), missing))
    rows.sort(key=lambda x: (-x[0], x[1]))
    for n, rid, total, missing in rows[: args.top]:
        print(f"{rid}\t{n}/{total} empty\t{', '.join(missing)}")
    print(f"# {len(rows)} records with empty fields among: {', '.join(args.field) if args.field else 'all fields'}",
          file=sys.stderr)


def short(v, n=100):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 3] + "..."


def cmd_diff(_, args):
    old, new = (json.loads(Path(p).read_text()) for p in (args.old, args.new))
    changed = 0
    for k in list(dict.fromkeys([*old, *new])):
        a, b = old.get(k), new.get(k)
        if a == b:
            continue
        changed += 1
        if is_empty(a):
            print(f"+ {k}: {short(b)}")
        elif is_empty(b):
            print(f"- {k}: {short(a)}  (REMOVED)")
        elif k == "benchmarks":
            key = lambda x: (x.get("dataset"), x.get("task"))  # noqa: E731
            ka, kb = {key(x) for x in a}, {key(x) for x in b}
            print(f"~ benchmarks: +{len(kb - ka)} new, -{len(ka - kb)} removed, "
                  f"{sum(1 for x in b if key(x) in ka and x not in a)} changed")
            for d, t in sorted(kb - ka, key=str):
                print(f"    + {d} / {t}")
            for d, t in sorted(ka - kb, key=str):
                print(f"    - {d} / {t}  (REMOVED)")
        else:
            print(f"~ {k}: {short(a, 60)} -> {short(b, 60)}")
    print(f"# {changed} field(s) changed", file=sys.stderr)


INDEX_HEADER = """# Catalog index

Generated by `scripts/catalog.py write-index` from the records in `models/` and
`embeddings/`; do not edit by hand. One row per record; open `<folder>/<id>.json`
for details. `?` = not stated in the record.

## Models

- **kind**: `encoder` or `vision-language` (has a text modality)
- **inputs**: modalities; sensors
- **time**: temporal alignment (`none` = single date, `partial`, `full` = time series), then the years of the training data when known
- **code**, **weights**: `y` if the record links source code / released weights

| id | name | kind | params | inputs | res | time | coverage | code | weights |
|---|---|---|---|---|---|---|---|---|---|
"""

PRODUCTS_HEADER = """
## Embedding products

Precomputed embeddings: no inference needed. `encoder` is the model id in
`models/` when there is one, else the model name.

- **type**: `pixel` (one vector per pixel) or `chip` (one vector per patch); **dims**: vector size
- **spacing**: ground distance between neighbouring vectors; **period**: ISO 8601 period each vector summarises (`snapshot` = single scene or mosaic)

| id | title | encoder | type | dims | dtype | sensors | spacing | period | years | coverage | license | hosting |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
"""


def cell(v):
    s = ", ".join(map(str, v)) if isinstance(v, list) else str(v or "")
    return s.replace("|", "/").replace("\n", " ").strip() or "?"


def model_row(r):
    mods, sens = cell(r.get("modalities")), r.get("supported_sensors")
    inputs = f"{mods}; {cell(sens)}" if sens else mods
    start, end = (r.get("start_datetime") or "")[:4], (r.get("end_datetime") or "")[:4]
    time = cell(r.get("temporal_alignment")) + (f", {start}-{end}" if start and end else "")
    assets = r.get("assets") or {}
    return [
        cell(r.get("id")), cell(r.get("mlm:name")), kind(r), fmt_count(r.get("mlm:total_parameters")),
        inputs, cell(r.get("spatial_resolution")), time, cell(r.get("regions_coverage")),
        "y" if "mlm:source_code" in assets else "n", "y" if "weights" in assets else "n",
    ]


def product_row(r):
    enc = r.get("encoder_model") or {}
    start, end = (r.get("start_datetime") or "")[:4], (r.get("end_datetime") or "")[:4]
    dtype = cell(r.get("data_type")) + (f" (from {r['emb:original_data_type']})" if r.get("emb:original_data_type") else "")
    return [
        cell(r.get("id")), cell(r.get("title")), cell(enc.get("id") or enc.get("name")), cell(r.get("emb:type")),
        "x".join(map(str, r.get("emb:dimensions") or [])) or "?", dtype, cell(r.get("source_sensors")),
        cell(r.get("spatial_resolution")), r.get("emb:temporal_period") or "snapshot",
        f"{start}-{end or 'ongoing'}" if start else "?", cell(r.get("regions_coverage")), cell(r.get("license")),
        cell(r.get("hosting")),
    ]


def cmd_write_index(db, _):
    recs = [r for _f, r in load(db)]
    models = ["| " + " | ".join(model_row(r)) + " |" for r in recs if not is_product(r)]
    products = ["| " + " | ".join(product_row(r)) + " |" for r in recs if is_product(r)]
    out = db / "INDEX.md"
    out.write_text(INDEX_HEADER + "\n".join(models) + "\n" + PRODUCTS_HEADER + "\n".join(products) + "\n")
    print(f"wrote {out} ({len(models)} models, {len(products)} embedding products)", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    sub.add_parser("write-index")
    c = sub.add_parser("check")
    c.add_argument("queries", nargs="+")
    g = sub.add_parser("gaps")
    g.add_argument("--field", action="append", help="only count these fields (repeatable)")
    g.add_argument("--kind", choices=list(SCHEMAS), help="only models or only embedding products")
    g.add_argument("--top", type=int, default=30)
    d = sub.add_parser("diff")
    d.add_argument("old")
    d.add_argument("new")
    args = p.parse_args()
    cmds = {"index": cmd_index, "check": cmd_check, "gaps": cmd_gaps, "write-index": cmd_write_index,
            "diff": cmd_diff}
    cmds[args.cmd](args.db, args)


if __name__ == "__main__":
    main()
