"""tools/apply_decisions.py --area: another area's confirmed hours go to overrides/<area>/."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apply_decisions  # noqa: E402

DECISIONS = [
    {"id": "n1", "status": "confirmed", "hours": "Mo-Su 08:00-23:00", "source": "https://example.com/visit"},
    {"id": "n2", "status": "closed", "source": "https://example.com/", "note": "The page says it closed in October."},
    {"id": "n3", "status": "confirmed", "hours": "Mo-Su 08:00-23:00", "source": "https://www.yelp.com/biz/example"},
]


def _run(tmp_path, *more):
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps(DECISIONS))
    out = tmp_path / "overrides"
    apply_decisions.main([str(decisions), "--osm", str(tmp_path / "no-pull.json"), "--folder", str(out), *more])
    return out


def test_another_areas_records_go_to_its_own_folder(tmp_path, capsys):
    out = _run(tmp_path, "--area", "chicago")
    assert sorted(p.name for p in (out / "chicago").iterdir()) == ["n1.json", "n2.json"]
    assert not list(out.glob("*.json")), "nothing of Chicago's belongs in New York's folder"
    rec = json.loads((out / "chicago" / "n1.json").read_text())
    assert rec["src"] == "shop" and rec["hours"][0] == [[480, 1380]]
    assert json.loads((out / "chicago" / "n2.json").read_text())["closed"] is True
    assert "SKIP n3: source not allowed" in capsys.readouterr().out          # a listing site, in any area


def test_without_area_the_records_are_new_yorks(tmp_path):
    out = _run(tmp_path)
    assert sorted(p.name for p in out.glob("*.json")) == ["n1.json", "n2.json"]
