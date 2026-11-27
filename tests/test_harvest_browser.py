"""tools/harvest_browser.mjs on a saved page served from this machine.

Skipped where there is no Node, no Playwright or no browser (the tests
workflow on GitHub has none of them): the reader never downloads one. The
page draws its hours by script a second after it loads, and hides three
lines the ways a stylesheet can that the plain reader cannot see.
"""
import functools
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "harvest"
CHROME = os.environ.get("LATECUP_CHROME") or str(Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1255"
                                                 / "chrome-headless-shell-mac-arm64/chrome-headless-shell")


def _node_path():
    if not shutil.which("node") or not shutil.which("npm") or not Path(CHROME).exists():
        return None
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    return root if (Path(root) / "playwright").exists() else None


NODE_PATH = _node_path()
pytestmark = pytest.mark.skipif(NODE_PATH is None, reason="no Node, Playwright or browser on this machine")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def served():
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(FIX)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_the_browser_reads_what_a_person_sees(served, tmp_path):
    cands = [{"id": "n1", "name": "Example Matcha", "addr": "1693 North Milpitas Boulevard", "city": "Milpitas",
              "web": f"{served}/drawn_by_script.html"},
             {"id": "n2", "name": "Gone", "addr": "1 Main St", "web": f"{served}/gone/old-page.html"}]
    (tmp_path / "c.json").write_text(json.dumps(cands))
    env = dict(os.environ, NODE_PATH=NODE_PATH, LATECUP_PYTHON=sys.executable, LATECUP_CHROME=CHROME)
    done = subprocess.run(["node", str(ROOT / "tools" / "harvest_browser.mjs"), str(tmp_path / "c.json"),
                           str(tmp_path / "out")], env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    rec = json.loads((tmp_path / "out" / "n1.json").read_text())
    assert rec["read_with"] == "browser" and rec["error"] is None
    text = "\n".join(rec["pages"][0]["block"])
    assert "Fri - Sat 12pm - 11pm" in text and "Checking hours" not in text       # drawn by the script
    for gone in ("1am - 2am", "3am - 4am", "5am - 6am"):                           # clipped, off the page, transparent
        assert gone not in json.dumps(rec["pages"][0]["snippets"] + rec["pages"][0]["block"] + rec["pages"][0]["text"])
    # what the page loaded as it ran is kept apart from what it showed, and says where it came from
    loaded = [g for g in rec["pages"][0]["script_data"] if g.get("from", "").endswith("/store-hours.json")]
    assert loaded and loaded[0]["near"] == "1693 N Milpitas Blvd" and loaded[0]["lines"][0].startswith("Monday:")
    assert "Fri - Sat 12pm - 11pm" in rec["pages"][0]["text"]
    # a page that is not there: the front page instead, two loads in all
    gone = json.loads((tmp_path / "out" / "n2.json").read_text())
    assert gone["error"] == "HTTP 404" and [p["url"] for p in gone["pages"]] == [f"{served}/"]


def test_without_a_browser_it_stops_and_says_so(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps([{"id": "n1", "name": "x", "web": "https://example.com/"}]))
    env = dict(os.environ, NODE_PATH=NODE_PATH, LATECUP_PYTHON=sys.executable,
               LATECUP_CHROME=str(tmp_path / "no-such-browser"))
    done = subprocess.run(["node", str(ROOT / "tools" / "harvest_browser.mjs"), str(tmp_path / "c.json"),
                           str(tmp_path / "out")], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "no browser at" in done.stderr and "Nothing was downloaded" in done.stderr
    assert not (tmp_path / "out" / "n1.json").exists()
