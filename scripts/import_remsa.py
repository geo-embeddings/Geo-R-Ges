"""Convert RS-FMD (REMSA) model records into skill/database/models/<id>.json.

Reads the vendored copy at sources/remsa/fmd.jsonl (kept outside the shipped skill)
and writes one record per model following skill/schema/model_schema_mlm.json. Anything converted
on a guess, or that does not fit the schema, is listed in the record's
provenance.review and in sources/remsa/import_report.md.

    uv run python scripts/import_remsa.py
"""

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sources" / "remsa" / "fmd.jsonl"
OUT = ROOT / "skill" / "database" / "models"
REPORT = ROOT / "sources" / "remsa" / "import_report.md"

REMSA_COMMIT = "7de853e5e9cb55bc54956c9c17f0cc4c017a2154"
SOURCE_URL = f"https://github.com/be-chen/REMSA/blob/{REMSA_COMMIT}/data/fmd.jsonl"
RETRIEVED = "2026-10-28T00:00:00Z"

# Substring of a review item -> category shown in the report summary.
REVIEW_KINDS = {
    "bands not assigned": "Bands not assigned to sensors",
    "pretraining phases flattened": "Several pretraining phases flattened",
    "values for one metric name": "Benchmark: several values for one metric name",
    "metric names but": "Benchmark: metric/value count mismatch, values cleared",
    "num_parameters": "Parameter count read as millions",
    "masking_ratio": "Mask ratio read as percent",
    "time_range": "Pretraining time range not parsed",
    "paper link": "Paper link without DOI",
    "modalities include Text": "Possibly Cross-domain Multimodal",
}

BENCHMARK_FIELDS = [
    "task", "application", "dataset", "metrics", "metrics_value",
    "sensor", "regions", "image_resolution", "spatial_resolution", "split_ratio",
]


def strs(items):
    """RS-FMD writes unknown lists as [null]; drop the nulls, and return None if nothing is left."""
    out = [x for x in items or [] if x is not None]
    return out or None


def to_datetime(date):
    if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return f"{date}T00:00:00Z"
    return None


def to_doi(url, review):
    if not url:
        return None
    m = re.fullmatch(r"https?://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?", url)
    if m:
        return f"10.48550/arXiv.{m.group(1)}"
    m = re.fullmatch(r"https?://(?:dx\.)?doi\.org/(10\..+)", url)
    if m:
        return m.group(1)
    review.append(f"paper link {url} is not an arXiv or DOI URL; look up the DOI")
    return None


def to_parameters(value, review):
    if value is None:
        return None
    if value < 1e5:
        review.append(f"num_parameters {value} read as millions -> {int(round(value * 1e6))}")
        value *= 1e6
    return int(round(value))


def to_mask_ratio(value, review):
    if value is None:
        return None
    if value > 1:
        review.append(f"masking_ratio {value} read as percent -> {value / 100}")
        return value / 100
    return value


def to_time_range(text, review):
    """Parse only unambiguous year or year-month ranges."""
    if not text:
        return None, None
    t = text.strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?\s*(?:-|–|to)\s*(\d{4})(?:-(\d{2}))?", t)
    if m:
        y1, m1, y2, m2 = m.groups()
        end_month = int(m2 or 12)
        end_day = 31 if end_month in (1, 3, 5, 7, 8, 10, 12) else 30 if end_month != 2 else 28
        return f"{y1}-{m1 or '01'}-01T00:00:00Z", f"{y2}-{end_month:02d}-{end_day}T23:59:59Z"
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return f"{t}-01-01T00:00:00Z", f"{t}-12-31T23:59:59Z"
    review.append(f"time_range '{text}' not parsed into start/end_datetime")
    return None, None


def to_size(text):
    """'224x224' -> 224; anything else -> None."""
    m = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", text or "")
    if m and m.group(1) == m.group(2):
        return int(m.group(1))
    return None


def pick_primary_phase(phases):
    """The phase with the most images, else the last (usually the final, largest stage)."""
    with_count = [p for p in phases if p.get("num_images")]
    if with_count:
        return max(with_count, key=lambda p: p["num_images"])
    return phases[-1]


def describe_phase(p):
    parts = [p.get("dataset") or "unnamed dataset"]
    for key, label in [("image_resolution", "input"), ("token_size", "patch"), ("epochs", "epochs"),
                       ("batch_size", "batch"), ("num_images", "images")]:
        if p.get(key) is not None:
            parts.append(f"{label} {p[key]}")
    return ", ".join(str(x) for x in parts)


def build_input(r, phase, review):
    sensors = strs(r.get("supported_sensors")) or []
    bands = strs(r.get("bands")) or []
    if not sensors:
        return None
    if len(sensors) > 1:
        if bands:
            review.append("bands not assigned to sensors (RS-FMD lists one band set for all sensors): "
                          + ", ".join(bands))
        return [{"name": s} for s in sensors]
    entry = {"name": sensors[0]}
    if bands:
        entry["bands"] = bands
        size = to_size(phase.get("image_resolution")) if phase else None
        plain_bands = all(re.fullmatch(r"[A-Za-z0-9_]+", b) for b in bands)
        if size and plain_bands:
            entry["input"] = {"shape": [-1, len(bands), size, size],
                              "dim_order": ["batch", "bands", "height", "width"]}
    return [entry]


def build_benchmarks(r, review):
    out = []
    for b in r.get("benchmarks") or []:
        if not b:
            continue
        bench = {k: b.get(k) for k in BENCHMARK_FIELDS}
        bench["sensor"], bench["regions"] = strs(b.get("sensor")), strs(b.get("regions"))
        metrics, values = bench["metrics"] or [], bench["metrics_value"] or []
        if len(metrics) != len(values):
            if len(metrics) == 1 and len(values) > 1:
                n = len(values)
                bench["metrics"] = [f"{metrics[0]} (setting {i + 1} of {n}, unlabelled in source)"
                                    for i in range(n)]
                review.append(f"benchmark {b.get('dataset')}: {n} values for one metric name "
                              f"'{metrics[0]}'; label the settings")
            else:
                bench["metrics_value"] = [None] * len(metrics)
                review.append(f"benchmark {b.get('dataset')}: {len(metrics)} metric names but "
                              f"{len(values)} values {values}; values cleared, re-enter from paper")
        out.append(bench)
    return out


def convert(r):
    review = []
    phases = [p for p in r.get("pretraining_phases") or [] if p]
    phase = pick_primary_phase(phases) if phases else {}

    pretraining = r.get("pretraining")
    if len(phases) > 1:
        others = [describe_phase(p) for p in phases if p is not phase]
        pretraining = (pretraining or "").rstrip() + (
            f" Pretraining has {len(phases)} phases; fields below describe '{phase.get('dataset')}'. "
            "Other phases: " + "; ".join(others) + ".")
        review.append(f"{len(phases)} pretraining phases flattened to '{phase.get('dataset')}'")

    start, end = to_time_range(phase.get("time_range"), review)
    regions = []
    for p in phases:
        for reg in strs(p.get("regions_coverage")) or []:
            if reg not in regions:
                regions.append(reg)
    datasets = [p["dataset"] for p in phases if p.get("dataset")]

    assets = {}
    if r.get("repository"):
        assets["mlm:source_code"] = {"href": r["repository"], "title": "Source code or project page",
                                     "roles": ["mlm:source_code", "code"]}
    if r.get("weights"):
        assets["weights"] = {"href": r["weights"], "title": "Pretrained weights",
                             "roles": ["mlm:weights"]}
    if r.get("paper_link"):
        assets["paper"] = {"href": r["paper_link"], "title": "Paper", "roles": ["metadata"]}

    modalities = strs(r.get("modalities")) or []
    if "Text" in modalities and r.get("modality_integration_type") != "Cross-domain Multimodal":
        review.append(f"modalities include Text but modality_integration_type is "
                      f"'{r.get('modality_integration_type')}'; consider 'Cross-domain Multimodal'")

    lr = phase.get("learning_rate")
    record = {
        "id": r["model_id"],
        "mlm:name": r["model_name"],
        "version": r.get("version"),
        "release_date": to_datetime(r.get("release_date")),
        "updated": to_datetime(r.get("last_updated")),
        "description": r.get("short_description"),
        "sci:doi": to_doi(r.get("paper_link"), review),
        "license": None,
        "assets": assets or None,
        "mlm:architecture": r.get("backbone"),
        "mlm:total_parameters": to_parameters(r.get("num_parameters"), review),
        "pretext_training_type": r.get("pretext_training_type"),
        "masking_strategy": r.get("masking_strategy"),
        "pretraining": pretraining,
        "domain_knowledge": strs(r.get("domain_knowledge")),
        "backbone_modifications": strs(r.get("backbone_modifications")),
        "supported_sensors": strs(r.get("supported_sensors")),
        "modality_integration_type": r.get("modality_integration_type"),
        "modalities": modalities or None,
        "spectral_alignment": r.get("spectral_alignment"),
        "temporal_alignment": r.get("temporal_alignment"),
        "spatial_resolution": r.get("spatial_resolution"),
        "temporal_resolution": r.get("temporal_resolution"),
        "mlm:input": build_input(r, phase, review),
        "mlm:pretrained_source": "; ".join(datasets) or None,
        "regions_coverage": regions or None,
        "start_datetime": start,
        "end_datetime": end,
        "num_images": phase.get("num_images"),
        "sampling": phase.get("sampling"),
        "processing:level": phase.get("processing_level"),
        "processing:lineage": "; ".join(strs(phase.get("processing")) or []) or None,
        "cloud_cover": phase.get("cloud_cover"),
        "missing_data": phase.get("missing_data"),
        "mlm:hyperparameters": {
            "patch_size": phase.get("token_size"),
            "epochs": phase.get("epochs"),
            "batch_size": phase.get("batch_size"),
            "learning_rate": None if lr is None else str(lr),
            "augmentations": strs(phase.get("augmentations")),
            "mask_ratio": to_mask_ratio(phase.get("masking_ratio"), review),
        } if phase else None,
        "benchmarks": build_benchmarks(r, review),
    }
    record["provenance"] = {
        "source": "RS-FMD (REMSA)",
        "source_id": r["model_id"],
        "source_url": SOURCE_URL,
        "retrieved": RETRIEVED,
        "review": review,
    }
    return record


def main():
    rows = [json.loads(line) for line in SRC.read_text().splitlines() if line.strip()]
    seen = {}
    records = []
    dropped = []
    for line_no, r in enumerate(rows, 1):
        if r["model_id"] in seen:
            # Two extractions of the same model; the first has the cleaner text.
            dropped.append((r["model_id"], line_no, seen[r["model_id"]]))
            continue
        seen[r["model_id"]] = line_no
        records.append(convert(r))

    for old in OUT.glob("*.json"):
        if json.loads(old.read_text()).get("provenance", {}).get("source") == "RS-FMD (REMSA)":
            old.unlink()
    for rec in records:
        (OUT / f"{rec['id']}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    by_kind = defaultdict(set)
    for rec in records:
        for item in rec["provenance"]["review"]:
            kind = next((k for k in REVIEW_KINDS if k in item), "other")
            by_kind[REVIEW_KINDS.get(kind, "other")].add(rec["id"])
    lines = [
        "# RS-FMD (REMSA) import report",
        "",
        f"Source: {SOURCE_URL}",
        f"Rows read: {len(rows)}. Records written: {len(records)}.",
        "",
        "Generated by `scripts/import_remsa.py`. Per-record details are in each record's `provenance.review`.",
        "",
        "## Dropped duplicates",
        "",
    ]
    lines += [f"- `{mid}`: line {ln} dropped, kept line {kept}" for mid, ln, kept in dropped] or ["- none"]
    flagged = [rec for rec in records if rec["provenance"]["review"]]
    lines += ["", "## Summary", "", "| Issue | Records |", "| --- | --- |"]
    lines += [f"| {kind} | {len(ids)} |" for kind, ids in sorted(by_kind.items(), key=lambda kv: -len(kv[1]))]
    lines += ["", "## Records needing review", ""]
    lines.append(f"{len(flagged)} of {len(records)} records have open review items.")
    lines.append("")
    for rec in flagged:
        lines.append(f"### `{rec['id']}`")
        lines += [f"- {item}" for item in rec["provenance"]["review"]]
        lines.append("")
    REPORT.write_text("\n".join(lines))
    print(f"wrote {len(records)} records, {len(flagged)} flagged, {len(dropped)} duplicates dropped")


if __name__ == "__main__":
    main()
