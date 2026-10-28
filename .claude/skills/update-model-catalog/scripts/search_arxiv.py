"""List recent arXiv papers that may introduce geospatial foundation models or
embedding products, skipping those already in model_metadata/.

Usage:
  python search_arxiv.py [--since YYYY-MM-DD] [--max 300] [--all] [--root DIR] [--query Q]

--since defaults to 30 days before the newest release_date in the catalog.
--all also prints papers that are already catalogued (status = matching file).
Output: one tab-separated line per paper: status, arXiv id, submitted date, title.
This is a recall-oriented keyword search: most hits are NOT foundation models
and must be screened by reading the abstract.
"""

import argparse
import datetime as dt
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from catalog import find_root, load, matches  # noqa: E402

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
DEFAULT_QUERY = (
    '(abs:"foundation model" OR abs:"pretrained model" OR abs:"pre-trained model" '
    'OR abs:"self-supervised" OR abs:"embeddings" OR abs:"representation learning") '
    'AND (abs:"remote sensing" OR abs:"earth observation" OR abs:"satellite" OR abs:"geospatial") '
    "AND (cat:cs.CV OR cat:cs.LG OR cat:eess.IV OR cat:cs.AI)"
)


def fetch(query, start, n):
    params = urllib.parse.urlencode({
        "search_query": query, "start": start, "max_results": n,
        "sortBy": "submittedDate", "sortOrder": "descending"})
    with urllib.request.urlopen(f"{API}?{params}", timeout=60) as resp:
        root = ET.fromstring(resp.read())
    for e in root.findall("a:entry", NS):
        yield {
            "id": e.findtext("a:id", "", NS).rsplit("/abs/", 1)[-1].rsplit("v", 1)[0],
            "date": e.findtext("a:published", "", NS)[:10],
            "title": " ".join(e.findtext("a:title", "", NS).split()),
        }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since")
    p.add_argument("--max", type=int, default=300)
    p.add_argument("--all", action="store_true")
    p.add_argument("--query", default=DEFAULT_QUERY)
    p.add_argument("--root", type=Path)
    args = p.parse_args()

    recs = load(args.root or find_root(Path.cwd().resolve()))
    since = args.since
    if not since:
        dates = [r["release_date"][:10] for _, r in recs if r.get("release_date")]
        newest = dt.date.fromisoformat(max(dates)) if dates else dt.date.today() - dt.timedelta(days=365)
        since = (newest - dt.timedelta(days=30)).isoformat()
    print(f"# arXiv papers submitted since {since}", file=sys.stderr)

    seen = 0
    while seen < args.max:
        batch = list(fetch(args.query, seen, min(100, args.max - seen)))
        if not batch:
            break
        for paper in batch:
            if paper["date"] < since:
                return
            hits = matches(paper["id"], recs) or matches(paper["title"].split(":")[0], recs)
            if hits and not args.all:
                continue
            status = ",".join(n for n, _ in hits) if hits else "NEW"
            print(f"{status}\t{paper['id']}\t{paper['date']}\t{paper['title']}")
        seen += len(batch)
        time.sleep(3)  # arXiv API asks for >= 3 s between requests


if __name__ == "__main__":
    main()
