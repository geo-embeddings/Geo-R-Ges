"""Inspect and validate the model_metadata/ catalog.

Usage:
  python catalog.py index                  # one line per record: id, name, arXiv/DOI, release date
  python catalog.py check QUERY [QUERY..]  # is a model (name, arXiv id, DOI or URL) already catalogued?
  python catalog.py validate [FILE ..]     # validate records against model_schema_mlm.json (default: all)

Options: --root DIR  repo root holding model_metadata/ and model_schema_mlm.json
         (default: nearest parent of the cwd that has model_schema_mlm.json)
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path


def find_root(start):
    for d in [start, *start.parents]:
        if (d / "model_schema_mlm.json").exists():
            return d
    sys.exit("model_schema_mlm.json not found in cwd or its parents; pass --root")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def arxiv_id(s):
    m = re.search(r"(\d{4}\.\d{4,5})", s or "")
    return m.group(1) if m else None


def load(root):
    recs = []
    for f in sorted((root / "model_metadata").glob("*.json")):
        try:
            recs.append((f, json.loads(f.read_text())))
        except json.JSONDecodeError as e:
            print(f"WARN {f.name}: invalid JSON ({e})", file=sys.stderr)
    return recs


def cmd_index(root, _):
    for f, r in load(root):
        doi = r.get("sci:doi") or ""
        ref = f"arXiv:{arxiv_id(doi)}" if "arxiv" in doi.lower() else (doi or "-")
        date = (r.get("release_date") or "-")[:10]
        print(f"{r.get('id')}\t{r.get('mlm:name')}\t{ref}\t{date}")


def matches(query, recs):
    """Return [(filename, reason)] for records that look like the queried model."""
    q_arx, q_norm = arxiv_id(query), norm(query)
    q_doi = query.lower().removeprefix("https://doi.org/")
    q_url = query.lower().rstrip("/") if query.startswith("http") else None
    hits = []
    for f, r in recs:
        doi = (r.get("sci:doi") or "").lower()
        names = [norm(r.get("mlm:name")), norm(r.get("id"))]
        urls = " ".join(a.get("href", "") for a in (r.get("assets") or {}).values()).lower()
        if q_arx and (q_arx == arxiv_id(doi) or q_arx in urls):
            hits.append((f.name, "arXiv id"))
        elif doi and q_doi == doi:
            hits.append((f.name, "DOI"))
        elif q_url and q_url in urls:
            hits.append((f.name, "URL"))
        elif q_norm and q_norm in names:
            hits.append((f.name, "exact name"))
        elif q_norm and not q_url and max(difflib.SequenceMatcher(None, q_norm, n).ratio() for n in names) >= 0.85:
            hits.append((f.name, "similar name"))
    return hits


def cmd_check(root, args):
    recs = load(root)
    for q in args.queries:
        hits = matches(q, recs)
        print(f"{q}: " + ("; ".join(f"{n} ({why})" for n, why in hits) if hits else "NEW"))


def cmd_validate(root, args):
    try:
        import jsonschema
    except ImportError:
        sys.exit("jsonschema missing: run with `uv run --with jsonschema python catalog.py validate ...`")
    schema = json.loads((root / "model_schema_mlm.json").read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    files = [Path(p) for p in args.files] or sorted((root / "model_metadata").glob("*.json"))
    bad = 0
    for f in files:
        try:
            r = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            print(f"FAIL {f.name}: invalid JSON ({e})")
            bad += 1
            continue
        errs = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                for e in validator.iter_errors(r)]
        if r.get("id") and f.stem != r["id"]:
            errs.append(f"filename '{f.stem}' != id '{r['id']}'")
        for i, b in enumerate(r.get("benchmarks") or []):
            if len(b.get("metrics") or []) != len(b.get("metrics_value") or []):
                errs.append(f"benchmarks/{i}: metrics and metrics_value differ in length")
        if errs:
            bad += 1
            print(f"FAIL {f.name}")
            for e in errs:
                print(f"  - {e}")
    print(f"{len(files) - bad}/{len(files)} valid")
    sys.exit(1 if bad else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    c = sub.add_parser("check")
    c.add_argument("queries", nargs="+")
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="*")
    args = p.parse_args()
    root = args.root or find_root(Path.cwd().resolve())
    {"index": cmd_index, "check": cmd_check, "validate": cmd_validate}[args.cmd](root, args)


if __name__ == "__main__":
    main()
