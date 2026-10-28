"""Convert REMSA model metadata (../REMSA/model_metadata/*_prediction.json)
to the RS-FMD MLM record schema (skill/schema/model_schema_mlm.json).

Usage: python scripts/convert_remsa.py [SRC_DIR] [OUT_DIR]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "REMSA" / "model_metadata"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "skill" / "database" / "models"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def unwrap(v):
    """Strip REMSA's {value, confidence} wrappers recursively."""
    if isinstance(v, dict) and set(v) <= {"value", "confidence"}:
        return unwrap(v.get("value"))
    if isinstance(v, list):
        return [unwrap(x) for x in v]
    if isinstance(v, dict):
        return {k: unwrap(x) for k, x in v.items()}
    if isinstance(v, str):
        # en dashes between digits were lost as '?' in the source files
        v = re.sub(r"(?<=\d)\?(?=\d)", "-", v).strip()
        return v or None
    return v


def clean(v):
    """Empty lists/strings mean 'not stated' -> null."""
    if isinstance(v, list):
        v = [x for x in v if x is not None]
        return v or None
    return v


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def timestamp(date):
    if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return f"{date}T00:00:00Z"
    return None


def doi_from_link(link):
    if not link:
        return None
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", link)
    if m:
        return f"10.48550/arXiv.{m.group(1)}"
    m = re.search(r"doi\.org/(10\.\d{4,}/\S+)", link)
    if m:
        return m.group(1)
    return None


def parameters(n):
    if n is None:
        return None
    # small values are counts in millions (e.g. 86 -> 86M, 0.4 -> 0.4M)
    return int(round(n * 1e6)) if n < 1e5 else int(n)


def parse_time_range(s):
    """Return (start, end) RFC 3339 timestamps, or None if not parseable."""
    if not s:
        return None
    t = s.replace("–", "-").replace("—", "-").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})", t)
    if m:
        return f"{m.group(1)}T00:00:00Z", f"{m.group(2)}T23:59:59Z"
    m = re.fullmatch(r"(\d{4})\s*(?:to|-)\s*(\d{4})", t)
    if m:
        return f"{m.group(1)}-01-01T00:00:00Z", f"{m.group(2)}-12-31T23:59:59Z"
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return f"{m.group(1)}-01-01T00:00:00Z", f"{m.group(1)}-12-31T23:59:59Z"
    m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})\s*(?:to|-)\s*([A-Za-z]+)\.?\s+(\d{4})", t)
    if m and m.group(1)[:3].lower() in MONTHS and m.group(3)[:3].lower() in MONTHS:
        m1, m2 = MONTHS[m.group(1)[:3].lower()], MONTHS[m.group(3)[:3].lower()]
        y2, m2n = (int(m.group(4)) + 1, 1) if m2 == 12 else (int(m.group(4)), m2 + 1)
        from datetime import date, timedelta
        last = date(y2, m2n, 1) - timedelta(days=1)
        return f"{m.group(2)}-{m1:02d}-01T00:00:00Z", f"{last.isoformat()}T23:59:59Z"
    return None


def parse_tile(s):
    """'120x120' / '96x96 pixels' -> (h, w); anything more complex -> None."""
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)(?:\s*(?:pixels|px))?", s.strip(), re.I)
    return (int(m.group(1)), int(m.group(2))) if m else None


def build_inputs(bands, sensors, tile, temporal):
    if not bands:
        return None
    groups = {}
    unnamed = []
    for b in bands:
        m = re.fullmatch(r"([^:]{1,40}):\s*(.+)", b)
        if m:
            parts = [p.strip() for p in m.group(2).split(",")]
            if not all(len(p) <= 12 for p in parts):
                parts = [m.group(2)]
            groups.setdefault(m.group(1).strip(), []).extend(parts)
        else:
            unnamed.append(b)
    if unnamed:
        name = sensors[0] if sensors and len(sensors) == 1 else (", ".join(sensors) if sensors else "unspecified")
        groups.setdefault(name, []).extend(unnamed)
    inputs = []
    for name, bs in groups.items():
        entry = {"name": name, "bands": bs}
        if tile:
            # band count only when every entry is a plain band identifier
            nb = len(bs) if all(re.fullmatch(r"[A-Za-z]{0,3}\d{0,2}[A-Za-z]?", x) for x in bs) else -1
            shape, dims = [-1, nb, *tile], ["batch", "bands", "height", "width"]
            if temporal in ("full", "partial"):
                shape.insert(1, -1)
                dims.insert(1, "time")
            entry["input"] = {"shape": shape, "dim_order": dims}
        inputs.append(entry)
    return inputs


def mask_ratio(r):
    if r is None:
        return None
    return round(r / 100, 4) if r > 1 else r


def stage(p):
    """Full record of an extra pretraining phase, in new field names."""
    d = {
        "mlm:pretrained_source": p.get("dataset"),
        "regions_coverage": clean(p.get("regions_coverage")),
        "time_range": p.get("time_range"),
        "num_images": p.get("num_images"),
        "sampling": p.get("sampling"),
        "processing:level": p.get("processing_level"),
        "processing:lineage": "; ".join(clean(p.get("processing")) or []) or None,
        "cloud_cover": p.get("cloud_cover"),
        "missing_data": p.get("missing_data"),
        "image_resolution": p.get("image_resolution"),
        "patch_size": p.get("token_size"),
        "epochs": p.get("epochs"),
        "batch_size": p.get("batch_size"),
        "learning_rate": p.get("learning_rate"),
        "augmentations": clean(p.get("augmentations")),
        "mask_ratio": mask_ratio(p.get("masking_ratio")),
    }
    return {k: v for k, v in d.items() if v is not None}


def benchmark(b):
    metrics = clean(b.get("metrics")) or []
    values = b.get("metrics_value") or []
    if len(metrics) == 1 and len(values) > 1:
        # one name, several settings: the source does not say which is which
        metrics = [f"{metrics[0]} (result {i + 1} of {len(values)})" for i in range(len(values))]
    elif len(values) < len(metrics):
        values = values + [None] * (len(metrics) - len(values))
    elif len(values) > len(metrics):
        metrics = metrics + [f"unnamed metric (result {i + 1})" for i in range(len(metrics), len(values))]

    split = b.get("split_ratio")
    n, total, pct = b.get("num_samples"), b.get("original_samples"), b.get("sampling_percentage")
    if n is not None or (pct is not None and pct != 100):
        used = f"samples used: {n}" if n is not None else "samples used:"
        if total is not None:
            used += f" of {total}"
        if pct is not None:
            used += f" ({pct}%)"
        split = f"{split}; {used}" if split else used

    return {
        "task": b.get("task"),
        "application": b.get("application"),
        "dataset": b.get("dataset"),
        "metrics": metrics or None,
        "metrics_value": values or None,
        "sensor": clean(b.get("sensor")),
        "regions": clean(b.get("regions")),
        "image_resolution": b.get("image_resolution"),
        "spatial_resolution": b.get("spatial_resolution"),
        "split_ratio": split,
    }


def convert(path):
    d = unwrap(json.loads(path.read_text()))
    phases = [p for p in (d.get("pretraining_phases") or []) if isinstance(p, dict)]
    p = phases[0] if phases else {}
    sensors = clean(d.get("supported_sensors"))

    assets = {}
    if d.get("repository"):
        assets["mlm:source_code"] = {"href": d["repository"], "title": "Source code",
                                     "type": "text/html", "roles": ["mlm:source_code", "code"]}
    if d.get("weights"):
        assets["weights"] = {"href": d["weights"], "title": "Model weights",
                             "roles": ["mlm:model", "mlm:weights"]}
    doi = doi_from_link(d.get("paper_link"))
    if d.get("paper_link") and not doi:
        assets["paper"] = {"href": d["paper_link"], "title": "Paper",
                           "type": "text/html", "roles": ["documentation"]}

    tile = parse_tile(p.get("image_resolution"))
    inputs = build_inputs(clean(d.get("bands")), sensors, tile, d.get("temporal_alignment"))

    sampling = p.get("sampling")
    times = parse_time_range(p.get("time_range"))
    if p.get("time_range") and not times:
        tr = f"Time range: {p['time_range']}"
        sampling = f"{sampling}; {tr}" if sampling else tr

    hp = {
        "patch_size": p.get("token_size"),
        "epochs": p.get("epochs"),
        "batch_size": p.get("batch_size"),
        "learning_rate": p.get("learning_rate"),
        "augmentations": clean(p.get("augmentations")),
        "mask_ratio": mask_ratio(p.get("masking_ratio")),
    }
    if p.get("image_resolution") and not (tile and inputs):
        hp["image_resolution"] = p["image_resolution"]
    if d.get("num_layers") is not None:
        hp["num_layers"] = d["num_layers"]
    if len(phases) > 1:
        hp["additional_pretraining_stages"] = [stage(x) for x in phases[1:]]

    return {
        "id": slug(path.name.removesuffix("_prediction.json")),
        "mlm:name": d["model_name"],
        "version": d.get("version"),
        "release_date": timestamp(d.get("release_date")),
        "updated": timestamp(d.get("last_updated")),
        "description": d.get("short_description"),
        "sci:doi": doi,
        "assets": assets or None,
        "mlm:architecture": d.get("backbone"),
        "mlm:total_parameters": parameters(d.get("num_parameters")),
        "pretext_training_type": d.get("pretext_training_type"),
        "masking_strategy": d.get("masking_strategy"),
        "pretraining": d.get("pretraining"),
        "domain_knowledge": clean(d.get("domain_knowledge")),
        "backbone_modifications": clean(d.get("backbone_modifications")),
        "supported_sensors": sensors,
        "modality_integration_type": d.get("modality_integration_type"),
        "modalities": clean(d.get("modalities")),
        "spectral_alignment": d.get("spectral_alignment"),
        "temporal_alignment": d.get("temporal_alignment"),
        "spatial_resolution": d.get("spatial_resolution"),
        "temporal_resolution": d.get("temporal_resolution"),
        "mlm:input": inputs,
        "mlm:pretrained_source": p.get("dataset"),
        "regions_coverage": clean(p.get("regions_coverage")),
        "start_datetime": times[0] if times else None,
        "end_datetime": times[1] if times else None,
        "num_images": p.get("num_images"),
        "sampling": sampling,
        "processing:level": p.get("processing_level"),
        "processing:lineage": "; ".join(clean(p.get("processing")) or []) or None,
        "cloud_cover": p.get("cloud_cover"),
        "missing_data": p.get("missing_data"),
        "mlm:hyperparameters": hp if any(v is not None for v in hp.values()) else None,
        "benchmarks": [benchmark(b) for b in d.get("benchmarks") or []] or None,
    }


def main():
    OUT.mkdir(exist_ok=True)
    seen = set()
    for path in sorted(SRC.glob("*_prediction.json")):
        rec = convert(path)
        assert rec["id"] not in seen, f"duplicate id {rec['id']}"
        seen.add(rec["id"])
        (OUT / f"{rec['id']}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(seen)} records to {OUT}")


if __name__ == "__main__":
    main()
