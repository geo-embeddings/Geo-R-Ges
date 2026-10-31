"""Shortlist catalogued geo foundation models for a use case.

Usage:
  python recommend.py candidates [--task KW ..] [--region KW ..] [--sensor KW ..]
                                 [--modality KW ..] [--max-params N] [--year YYYY]
                                 [--needs-weights] [--embeddings-only] [--all] [--top N]
  python recommend.py show ID [ID ..] [--task KW ..] [--region KW ..]
  python recommend.py leaderboard DATASET [--metric M]

candidates  scores every record against the constraints and prints the best matches,
            each with the evidence behind its score. Keywords are case-insensitive
            substrings; pass several (synonyms, country + continent, dataset names).
            Records over --max-params, or (with --needs-weights) without released
            weights, are dropped unless --all is given; unknown values are kept and
            flagged.
show        prints a compact card per record: kind, size, inputs, coverage, assets
            and the benchmarks matching --task / --region (all benchmarks if none).
leaderboard lists every catalogued result on one benchmark dataset (substring
            match), best first. Numbers come from each model's own paper, so the
            protocols (splits, label fractions, frozen vs fine-tuned) can differ.

--max-params accepts 400000, 85M, 1.5B. Options: --db DIR (catalog directory
holding models/ and embeddings/; default: the skill's own database/).
"""

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DB = SKILL_DIR / "database"
SCHEMAS = {"models": SKILL_DIR / "schema" / "model_schema_mlm.json",
           "embeddings": SKILL_DIR / "schema" / "embedding_schema_emb.json"}
GLOBAL = re.compile(r"\b(global|worldwide|world|all continents|over \d+ countries)\b", re.I)


def record_files(db=DB):
    """(subfolder, path) for every record: models/ first, then embeddings/."""
    for sub in SCHEMAS:
        for f in sorted((db / sub).glob("*.json")):
            yield sub, f


def load_files(db=DB):
    """[(path, record)] for every readable record."""
    recs = []
    for _sub, f in record_files(db):
        try:
            recs.append((f, json.loads(f.read_text())))
        except json.JSONDecodeError as e:
            print(f"WARN {f.name}: invalid JSON ({e})", file=sys.stderr)
    return recs


def load(db=DB):
    return [r for _f, r in load_files(db)]


def is_product(r):
    """Embedding product records (embedding_schema_emb.json) carry emb:type; model records do not."""
    return "emb:type" in r


def name(r):
    return r.get("mlm:name") or r.get("title")


def sensors(r):
    return r.get("supported_sensors") or r.get("source_sensors")


def parse_count(s):
    m = re.fullmatch(r"\s*([\d.]+)\s*([kmb]?)\s*", str(s), re.I)
    if not m:
        sys.exit(f"cannot parse parameter count {s!r}")
    return float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[m.group(2).lower()]


def fmt_count(n):
    if n is None:
        return "?"
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"{n / div:.3g}{unit}"
    return str(int(n))


def text(*vals):
    """Flatten strings / lists / dicts into one lowercase string."""
    out = []
    for v in vals:
        if isinstance(v, dict):
            out.append(text(*v.values()))
        elif isinstance(v, list):
            out.append(text(*v))
        elif v is not None:
            out.append(str(v))
    return " ".join(out).lower()


def hits(kws, s):
    return [k for k in kws if k.lower() in s]


def weights_url(r):
    """Released weights for a model; the main data asset (role 'embeddings') for a product."""
    assets = r.get("assets") or {}
    if is_product(r):
        return next((a.get("href") for a in assets.values() if "embeddings" in (a.get("roles") or [])), None)
    w = assets.get("weights")
    return w.get("href") if isinstance(w, dict) else None


def code_url(r):
    c = (r.get("assets") or {}).get("mlm:source_code")
    return c.get("href") if isinstance(c, dict) else None


def kind(r):
    if is_product(r):
        return "embedding-product"
    if "text" in text(r.get("modalities")):
        return "vision-language"
    return "encoder"


def bench_text(b):
    return text(b.get("task"), b.get("application"), b.get("dataset"))


def bench_region_text(b):
    return text(b.get("regions"), b.get("dataset"))


def score(r, a):
    """Return (score, reasons, flags, drop) for one record."""
    pts, why, flags = 0, [], []
    benches = r.get("benchmarks") or []

    if a.task:
        tb = [b for b in benches if hits(a.task, bench_text(b))]
        if tb:
            pts += 2 + min(len(tb), 4)
            why.append(f"{len(tb)} {'/'.join(a.task)} benchmark(s)")
        elif hits(a.task, text(r.get("description"), r.get("pretraining"))):
            pts += 1
            why.append("task in description")
        if a.region:
            local = [b for b in tb if hits(a.region, bench_region_text(b))]
            if local:
                pts += 4
                why.append("task benchmark in region: " + "; ".join(b.get("dataset") or "?" for b in local[:3]))

    if a.region:
        cov = text(r.get("regions_coverage"), r.get("mlm:pretrained_source"))
        if hits(a.region, cov):
            pts += 2
            why.append("region in pretraining coverage")
        elif GLOBAL.search(cov):
            pts += 1
            why.append("global pretraining")
        elif any(hits(a.region, bench_region_text(b)) for b in benches):
            pts += 1
            why.append("benchmarked in region")
        elif cov:
            flags.append("pretraining coverage excludes region")

    if a.sensor:
        sens = text(sensors(r), r.get("mlm:input"))
        h = hits(a.sensor, sens)
        if h:
            pts += 2
            why.append("sensor " + "/".join(h))
        elif sens:
            pts -= 2
            flags.append("sensor not listed")

    if a.modality:
        h = hits(a.modality, text(r.get("modalities")))
        if h:
            pts += 1
            why.append("modality " + "/".join(h))
        else:
            flags.append("modality not listed")

    drop = False
    n = r.get("mlm:total_parameters")
    k = kind(r)
    if a.max_params is not None:
        if k == "embedding-product":
            pts += 3
            why.append("precomputed embeddings (no inference needed)")
        elif n is None:
            flags.append("size unknown")
        elif n <= a.max_params:
            pts += 1 + (n <= a.max_params / 10)
        else:
            drop = True
            flags.append(f"too large ({fmt_count(n)})")

    if weights_url(r):
        pts += 1
    elif a.needs_weights:
        drop = True
        flags.append("no weights listed")
    if not code_url(r) and not weights_url(r):
        flags.append("no code or weights listed")

    if a.year:
        start, end = (r.get("start_datetime") or "")[:4], (r.get("end_datetime") or "")[:4]
        if k == "embedding-product":
            if start and int(start) > a.year:
                pts -= 3
                flags.append(f"data starts {start}")
            elif end and int(end) < a.year:
                pts -= 3
                flags.append(f"catalog lists data until {end}: check if {a.year} layer exists")
            elif start and not end:
                flags.append(f"ongoing product: check that the {a.year} layer is published")
            elif not start:
                flags.append("years not stated")
        elif end and a.year - int(end) >= 3:
            flags.append(f"pretraining data ends {end}")

    return pts, why, flags, drop


def cmd_candidates(recs, a):
    rows = []
    for r in recs:
        pts, why, flags, drop = score(r, a)
        if drop and not a.all:
            continue
        rows.append((pts, r, why, flags))
    rows.sort(key=lambda x: (-x[0], x[1].get("id") or ""))
    for pts, r, why, flags in rows[: a.top]:
        if is_product(r):
            dims = "x".join(map(str, r.get("emb:dimensions") or [])) or "?"
            print(f"{pts:>3}  {r.get('id')}  [{kind(r)}, {r.get('emb:type')} {dims}-d, "
                  f"{r.get('spatial_resolution') or '?'}, {'data' if weights_url(r) else '-'}, {years(r)}]")
        else:
            avail = "weights" if weights_url(r) else ("code" if code_url(r) else "-")
            print(f"{pts:>3}  {r.get('id')}  [{kind(r)}, {fmt_count(r.get('mlm:total_parameters'))}, "
                  f"{r.get('spatial_resolution') or '?'}, {avail}, {(r.get('release_date') or '?')[:10]}]")
        if why:
            print("       + " + "; ".join(why))
        if flags:
            print("       ! " + "; ".join(flags))
    print(f"\n{len(rows)} of {len(recs)} records kept; showing {min(a.top, len(rows))}", file=sys.stderr)


def years(r):
    start, end = (r.get("start_datetime") or "")[:4], (r.get("end_datetime") or "")[:4]
    if not start:
        return "years ?"
    return f"{start}-{end or 'ongoing'}"


def show_product(r, by_id):
    enc = r.get("encoder_model") or {}
    dims = "x".join(map(str, r.get("emb:dimensions") or [])) or "?"
    print(f"== {r.get('id')}: {name(r)} (embedding-product, {r.get('emb:type')})")
    print(f"   encoder {enc.get('name') or '?'} {enc.get('checkpoint') or ''}".rstrip()
          + (f" (model record: {enc['id']})" if enc.get("id") in by_id else ""))
    print(f"   {dims}-d {r.get('data_type') or '?'}"
          + (f" (from {r['emb:original_data_type']})" if r.get("emb:original_data_type") else "")
          + f", spacing {r.get('spatial_resolution') or '?'}, period {r.get('emb:temporal_period') or 'snapshot'}")
    print(f"   sensors {', '.join(sensors(r) or []) or '?'}; years {years(r)}; "
          f"regions {', '.join(r.get('regions_coverage') or []) or '?'}")
    if r.get("temporal_coverage_note"):
        print(f"   coverage note: {r['temporal_coverage_note']}")
    print(f"   license {r.get('license') or '?'}; hosting {', '.join(r.get('hosting') or []) or '?'}; "
          f"access {r.get('access_requirements') or '?'}")
    print(f"   data {weights_url(r) or '-'}")
    for ld in r.get("loaders") or []:
        print(f"   loader {ld}")
    print(f"   {r.get('description') or ''}")


def cmd_show(recs, a):
    by_id = {r.get("id"): r for r in recs}
    for i in a.ids:
        r = by_id.get(i)
        if not r:
            print(f"{i}: not found\n")
            continue
        if is_product(r):
            show_product(r, by_id)
            print()
            continue
        print(f"== {r.get('id')}: {r.get('mlm:name')} ({kind(r)})")
        print(f"   release {(r.get('release_date') or '?')[:10]}, doi {r.get('sci:doi') or '-'}")
        print(f"   size {fmt_count(r.get('mlm:total_parameters'))}, arch {r.get('mlm:architecture') or '?'}")
        print(f"   sensors {', '.join(r.get('supported_sensors') or []) or '?'}")
        print(f"   modalities {', '.join(r.get('modalities') or []) or '?'}; "
              f"gsd {r.get('spatial_resolution') or '?'}; time {r.get('temporal_resolution') or '?'}")
        print(f"   pretraining data {r.get('mlm:pretrained_source') or '?'}; "
              f"{(r.get('start_datetime') or '?')[:4]}-{(r.get('end_datetime') or '?')[:4]}; "
              f"regions {', '.join(r.get('regions_coverage') or []) or '?'}")
        print(f"   code {code_url(r) or '-'}\n   weights {weights_url(r) or '-'}")
        products = [p.get("id") for p in recs if is_product(p) and (p.get("encoder_model") or {}).get("id") == i]
        if products:
            print(f"   precomputed embeddings {', '.join(products)}")
        print(f"   {r.get('description') or ''}")
        benches = r.get("benchmarks") or []
        if a.task or a.region:
            benches = [b for b in benches if (a.task and hits(a.task, bench_text(b)))
                       or (a.region and hits(a.region, bench_region_text(b)))]
        for b in benches:
            vals = ", ".join(f"{m} {v}" for m, v in zip(b.get("metrics") or [], b.get("metrics_value") or []))
            reg = ", ".join(b.get("regions") or []) or "?"
            print(f"   - {b.get('application') or b.get('task')} | {b.get('dataset')} ({reg}) | {vals}")
        print()


def cmd_leaderboard(recs, a):
    rows = []
    for r in recs:
        for b in r.get("benchmarks") or []:
            if a.dataset.lower() not in (b.get("dataset") or "").lower():
                continue
            for m, v in zip(b.get("metrics") or [], b.get("metrics_value") or []):
                if v is None or (a.metric and a.metric.lower() != (m or "").lower()):
                    continue
                rows.append((m, v, r.get("id"), b.get("dataset"), b.get("application"), b.get("split_ratio")))
    rows.sort(key=lambda x: (x[0] or "", -x[1] if isinstance(x[1], (int, float)) else 0))
    for m, v, i, ds, app, split in rows:
        print(f"{m}\t{v}\t{i}\t{ds}\t{app}\t{split or ''}")
    if not rows:
        print(f"no results for dataset {a.dataset!r}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    s = sub.add_parser("show")
    s.add_argument("ids", nargs="+")
    for q in (c, s):
        q.add_argument("--task", action="append", default=[])
        q.add_argument("--region", action="append", default=[])
    c.add_argument("--sensor", action="append", default=[])
    c.add_argument("--modality", action="append", default=[])
    c.add_argument("--max-params", type=parse_count)
    c.add_argument("--year", type=int)
    c.add_argument("--needs-weights", action="store_true")
    c.add_argument("--embeddings-only", action="store_true")
    c.add_argument("--all", action="store_true")
    c.add_argument("--top", type=int, default=15)
    lb = sub.add_parser("leaderboard")
    lb.add_argument("dataset")
    lb.add_argument("--metric")
    a = p.parse_args()

    recs = load(a.db)
    if a.cmd == "candidates":
        if a.embeddings_only:
            recs = [r for r in recs if kind(r) == "embedding-product"]
        cmd_candidates(recs, a)
    elif a.cmd == "show":
        cmd_show(recs, a)
    else:
        cmd_leaderboard(recs, a)


if __name__ == "__main__":
    main()
