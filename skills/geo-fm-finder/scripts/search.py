"""Find recent papers that may introduce geospatial foundation models or embedding
products, across several literature sources, skipping those already in the
catalog (database/models/ and database/embeddings/).

Usage:
  python search.py [--since YYYY-MM-DD] [--sources arxiv,citations,openalex,s2,scholar]
                   [--max N] [--all] [--db DIR]

Sources (default: all):
  arxiv      arXiv API keyword search (preprints, newest first)
  openalex   OpenAlex keyword search (journals, conferences and arXiv)
  citations  OpenAlex: new papers citing models already in the catalog that also
             mention pretraining/foundation models; `cites` = how many catalogued
             models a paper cites (new foundation model papers compare against many)
  s2         Semantic Scholar bulk keyword search
  scholar    Google Scholar keyword search (HTML; few pages, slow, stops at captcha)

--since defaults to 30 days before the newest release_date in the catalog.
Optional env: OPENALEX_API_KEY (free key, https://openalex.org/settings/api; without
one, OpenAlex allows a small daily budget shared per IP, roughly one full run),
S2_API_KEY (Semantic Scholar, higher rate limit).

Output: tab-separated, one line per paper, merged across sources, sorted by cites
then date: status, sources, cites, ref (arXiv id / DOI / URL), date, venue, title.
Recall-oriented: most hits are NOT foundation models and must be screened.
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from catalog import DB, arxiv_id, load, matches, norm  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
METHOD_TERMS = ["foundation model", "pretrained", "pre-trained", "self-supervised",
                "embeddings", "representation learning", "vision-language"]
DOMAIN_TERMS = ["remote sensing", "earth observation", "satellite", "geospatial"]
SCHOLAR_QUERIES = [
    '"foundation model" "remote sensing"',
    '"foundation model" "earth observation"',
    '"geospatial foundation model"',
    '"embeddings" "earth observation" pretrained',
    '"self-supervised" pretraining "remote sensing" backbone',
]


def log(msg):
    print(f"# {msg}", file=sys.stderr)


def get(url, headers=None, retries=3):
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1 and int(e.headers.get("Retry-After") or 0) <= 60:
                time.sleep(5 * (attempt + 1))
                continue
            if e.code == 429:  # surface the API's own explanation (e.g. OpenAlex daily budget)
                e.msg += ": " + e.read()[:300].decode("utf-8", "replace")
            raise


def paper(source, title, date="", doi=None, arxiv=None, url=None, venue="", cites=0):
    doi = (doi or "").lower().removeprefix("https://doi.org/") or None
    arxiv = arxiv or arxiv_id(doi if doi and "arxiv" in doi else "") or None
    return {"sources": {source}, "title": " ".join((title or "").split()), "date": date or "",
            "doi": doi, "arxiv": arxiv, "url": url, "cites": cites,
            "venue": "arXiv" if (venue or "").lower().startswith("arxiv") else (venue or "")}


# --- sources -----------------------------------------------------------------

def search_arxiv(since, n):
    terms = lambda ts: " OR ".join(f'abs:"{t}"' for t in ts)  # noqa: E731
    q = f"({terms(METHOD_TERMS)}) AND ({terms(DOMAIN_TERMS)}) AND (cat:cs.CV OR cat:cs.LG OR cat:eess.IV OR cat:cs.AI)"
    ns = {"a": "http://www.w3.org/2005/Atom"}
    start = 0
    while start < n:
        params = urllib.parse.urlencode({"search_query": q, "start": start, "max_results": min(100, n - start),
                                         "sortBy": "submittedDate", "sortOrder": "descending"})
        entries = ET.fromstring(get(f"https://export.arxiv.org/api/query?{params}")).findall("a:entry", ns)
        if not entries:
            return
        for e in entries:
            date = e.findtext("a:published", "", ns)[:10]
            if date < since:
                return
            aid = e.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1].rsplit("v", 1)[0]
            yield paper("arxiv", e.findtext("a:title", "", ns), date, arxiv=aid, venue="arXiv")
        start += len(entries)
        time.sleep(3)  # arXiv asks for >= 3 s between requests


def openalex(params, n):
    params = {**params, "per_page": 200, "cursor": "*",
              "select": "id,doi,title,publication_date,primary_location,referenced_works,ids"}
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    seen = 0
    while params["cursor"] and seen < n:
        data = json.loads(get("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
        for w in data["results"]:
            yield w
        seen += len(data["results"])
        params["cursor"] = data["meta"].get("next_cursor") if data["results"] else None


def oa_paper(source, w, cites=0):
    src = ((w.get("primary_location") or {}).get("source") or {})
    landing = (w.get("primary_location") or {}).get("landing_page_url")
    return paper(source, w.get("title"), w.get("publication_date"), doi=w.get("doi"),
                 arxiv=arxiv_id(landing) if landing and "arxiv" in landing else None,
                 url=landing, venue=src.get("display_name") or "", cites=cites)


def oa_query():
    q = lambda ts: " OR ".join(f'"{t}"' for t in ts)  # noqa: E731
    return f"({q(METHOD_TERMS)}) AND ({q(DOMAIN_TERMS)})"


def search_openalex(since, n):
    for w in openalex({"filter": f"from_publication_date:{since},title_and_abstract.search:{oa_query()}",
                       "sort": "publication_date:desc"}, n):
        yield oa_paper("openalex", w)


def search_citations(since, n, recs):
    """New papers citing catalogued models, ranked by how many of them they cite."""
    dois = sorted({r["sci:doi"].lower() for _, r in recs if r.get("sci:doi")})
    seeds = set()
    for i in range(0, len(dois), 50):
        for w in openalex({"filter": "doi:" + "|".join(dois[i:i + 50])}, 50):
            seeds.add(w["id"])
    log(f"citations: {len(seeds)}/{len(dois)} catalogued papers found in OpenAlex")
    seed_list = sorted(seeds)
    found = {}
    for i in range(0, len(seed_list), 50):
        ids = "|".join(s.rsplit("/", 1)[-1] for s in seed_list[i:i + 50])
        flt = f"cites:{ids},from_publication_date:{since},title_and_abstract.search:{oa_query()}"
        for w in openalex({"filter": flt}, n):
            if w["id"] not in found:
                found[w["id"]] = (w, len(seeds & set(w.get("referenced_works") or [])))
    for w, c in found.values():
        yield oa_paper("citations", w, cites=c)


def search_s2(since, n):
    q = lambda ts: " | ".join(f'"{t}"' for t in ts)  # noqa: E731
    params = {"query": f"({q(METHOD_TERMS)}) + ({q(DOMAIN_TERMS)})", "publicationDateOrYear": f"{since}:",
              "fields": "title,externalIds,publicationDate,venue,url", "sort": "publicationDate:desc"}
    headers = {"x-api-key": os.environ["S2_API_KEY"]} if os.environ.get("S2_API_KEY") else {}
    seen = 0
    while seen < n:
        data = json.loads(get("https://api.semanticscholar.org/graph/v1/paper/search/bulk?"
                              + urllib.parse.urlencode(params), headers))
        for p in data.get("data") or []:
            ext = p.get("externalIds") or {}
            yield paper("s2", p.get("title"), p.get("publicationDate"), doi=ext.get("DOI"),
                        arxiv=ext.get("ArXiv"), url=p.get("url"), venue=p.get("venue"))
        seen += len(data.get("data") or [])
        if not data.get("token"):
            return
        params["token"] = data["token"]
        time.sleep(1)


class ScholarParser(HTMLParser):
    """Pull title, link and the authors/venue/year line out of Scholar result blocks."""

    def __init__(self):
        super().__init__()
        self.results, self.cur, self.field, self.depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag == "div" and "gs_ri" in cls.split():
            self.cur = {"title": "", "meta": "", "url": None}
            self.results.append(self.cur)
        elif self.cur is not None and tag == "h3" and "gs_rt" in cls:
            self.field, self.depth = "title", 1
        elif self.cur is not None and tag == "div" and cls == "gs_a":
            self.field, self.depth = "meta", 1
        elif self.field and tag in ("h3", "div"):
            self.depth += 1
        if self.field == "title" and tag == "a" and not self.cur["url"]:
            self.cur["url"] = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if self.field and tag in ("h3", "div"):
            self.depth -= 1
            if self.depth == 0:
                self.field = None

    def handle_data(self, data):
        if self.field:
            self.cur[self.field] += data


def search_scholar(since, n):
    query = {"as_ylo": since[:4], "hl": "en"}
    if dt.date.fromisoformat(since) > dt.date.today() - dt.timedelta(days=365):
        query["scisbd"] = 1  # sort by date added; Scholar only allows this for the past year
    per_query = max(1, min(3, n // (10 * len(SCHOLAR_QUERIES))))
    for q in SCHOLAR_QUERIES:
        for page in range(per_query):
            params = urllib.parse.urlencode({"q": q, **query, "start": page * 10})
            try:
                body = get(f"https://scholar.google.com/scholar?{params}").decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                log(f"scholar: HTTP {e.code}, stopping (likely rate limited)")
                return
            if "gs_captcha" in body or "unusual traffic" in body:
                log("scholar: captcha, stopping; rerun later or use the other sources")
                return
            parser = ScholarParser()
            parser.feed(body)
            if not parser.results:
                break
            for r in parser.results:
                title = re.sub(r"^\s*(\[[A-Z]+\]\s*)+", "", html.unescape(r["title"]))
                meta = " ".join(html.unescape(r["meta"]).split())  # also turns &nbsp; into spaces
                years = re.findall(r"\b(20\d\d)\b", meta)
                parts = [p.strip() for p in meta.split(" - ")]
                venue = re.sub(r",?\s*20\d\d$", "", parts[1]).strip("… ") if len(parts) > 2 else ""
                aid = arxiv_id(r["url"]) if r["url"] and "arxiv" in r["url"] else None
                # Scholar gives only a year; an arXiv id also encodes the month
                date = f"20{aid[:2]}-{aid[2:4]}" if aid else (years[-1] if years else "")
                yield paper("scholar", title, date, url=r["url"], arxiv=aid, venue=venue)
            time.sleep(8)  # stay well under Scholar's rate limits


# --- merging -----------------------------------------------------------------

def key(p):
    return p["arxiv"] or p["doi"] or norm(p["title"])[:80]


def merge(papers):
    """Merge duplicates across sources by arXiv id, DOI, or normalized title."""
    by_key, by_title = {}, {}
    for p in papers:
        t = norm(p["title"])[:80]
        hit = by_key.get(p["arxiv"]) or by_key.get(p["doi"]) or by_title.get(t)
        if hit is None:
            hit = p
        else:
            hit["sources"] |= p["sources"]
            hit["cites"] = max(hit["cites"], p["cites"])
            for f in ("doi", "arxiv", "url", "venue"):
                hit[f] = hit[f] or p[f]
            if hit.get("venue") == "arXiv" and p["venue"] and p["venue"] != "arXiv":
                hit["venue"] = p["venue"]
            hit["date"] = min(d for d in (hit["date"], p["date"]) if d) if (hit["date"] or p["date"]) else ""
        for k in (hit["arxiv"], hit["doi"]):
            if k:
                by_key[k] = hit
        by_title[t] = hit
    return list({id(p): p for p in [*by_key.values(), *by_title.values()]}.values())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since")
    p.add_argument("--sources", default="arxiv,citations,openalex,s2,scholar")
    p.add_argument("--max", type=int, default=300, help="max results per source")
    p.add_argument("--all", action="store_true", help="also print papers already catalogued")
    p.add_argument("--db", type=Path, default=DB)
    args = p.parse_args()

    recs = load(args.db)
    since = args.since
    if not since:
        dates = [r["release_date"][:10] for _, r in recs if r.get("release_date")]
        newest = dt.date.fromisoformat(max(dates)) if dates else dt.date.today() - dt.timedelta(days=365)
        since = (newest - dt.timedelta(days=30)).isoformat()
    log(f"papers published since {since}")

    runners = {
        "arxiv": lambda: search_arxiv(since, args.max),
        "openalex": lambda: search_openalex(since, args.max),
        "citations": lambda: search_citations(since, args.max, recs),
        "s2": lambda: search_s2(since, args.max),
        "scholar": lambda: search_scholar(since, args.max),
    }
    papers = []
    for name in args.sources.split(","):
        before = len(papers)
        try:
            papers.extend(runners[name.strip()]())
        except Exception as e:  # one failing source should not lose the others
            log(f"{name}: failed ({type(e).__name__}: {e})")
        log(f"{name}: {len(papers) - before} results")

    rows = []
    for x in merge(papers):
        if x["date"] and x["date"] < since[: len(x["date"])]:
            continue
        hits = []
        for q in (x["arxiv"], x["doi"], x["title"].split(":")[0]):
            if q and not hits:
                hits = matches(q, recs)
        if hits and not args.all:
            continue
        ref = f"arXiv:{x['arxiv']}" if x["arxiv"] else (x["doi"] or x["url"] or "-")
        status = ",".join(n for n, _ in hits) if hits else "NEW"
        rows.append((x["cites"], x["date"], status, ",".join(sorted(x["sources"])), ref, x["venue"], x["title"]))
    rows.sort(key=lambda r: r[1], reverse=True)  # newest first ...
    rows.sort(key=lambda r: r[0], reverse=True)  # ... within most catalogued models cited (stable)
    for cites, date, status, sources, ref, venue, title in rows:
        print("\t".join([status, sources, str(cites), ref, date or "-", venue or "-", title]))
    log(f"{len(rows)} papers listed")


if __name__ == "__main__":
    main()
