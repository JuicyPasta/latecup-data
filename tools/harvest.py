"""Fetch the shops' own sites and keep what they say about hours.

usage: python tools/harvest.py candidates.json out-folder [--workers 6]

candidates.json: [{id, name, addr, phone, web, ...}]. For each one: fetch the
site (and at most one same-site "hours / visit / locations" page), keep the
schema.org hours and the hour-like lines of visible text in out/<id>.json.
Nothing is decided here. One site is fetched once however many places share
it; two requests at most per site, 2 s apart.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import confirm as C  # noqa: E402


def read_site(url):
    """-> {pages: [{url, jsonld, lines}], error}"""
    out = {"pages": [], "error": None}
    s = requests.Session()
    try:
        final, page = C.fetch(url, s)
    except IOError as e:
        out["error"] = str(e)
        return out
    lines, links = C.visible(page)
    ld = C.jsonld_hours(page)
    out["pages"].append({"url": final, "jsonld": ld, "lines": lines})
    snip = C.snippets(lines)
    if not ld and len(snip) < 3:
        nxt = C.hours_link(final, links)
        if nxt and C.allowed(nxt):
            time.sleep(2)
            try:
                final2, page2 = C.fetch(nxt, s)
                lines2, _ = C.visible(page2)
                out["pages"].append({"url": final2, "jsonld": C.jsonld_hours(page2), "lines": lines2})
            except IOError as e:
                out["error"] = f"second page: {e}"
    return out


def main(argv):
    cands = json.loads(Path(argv[0]).read_text())
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 6
    by_url = {}
    for c in cands:
        if c.get("web") and C.allowed(c["web"]) and not (outdir / f"{c['id']}.json").exists():
            by_url.setdefault(c["web"], []).append(c)
    # one host at a time per worker: group urls by host so a host is never hit in parallel
    by_host = {}
    for url in by_url:
        by_host.setdefault(urlsplit(url).hostname, []).append(url)
    print(len(by_url), "sites on", len(by_host), "hosts")

    def do_host(urls):
        for n, url in enumerate(urls):
            if n:
                time.sleep(2)
            site = read_site(url)
            for c in by_url[url]:
                rec = {"id": c["id"], "name": c["name"], "addr": c.get("addr"), "phone": c.get("phone"),
                       "web": url, "error": site["error"], "pages": []}
                for pg in site["pages"]:
                    rec["pages"].append({"url": pg["url"], "jsonld": pg["jsonld"],
                                         "snippets": C.snippets(pg["lines"], c.get("addr"))})
                (outdir / f"{c['id']}.json").write_text(json.dumps(rec, ensure_ascii=False))
        return len(urls)

    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for n in ex.map(do_host, by_host.values()):
            done += n
            if done % 25 < n:
                print(done, "sites done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
