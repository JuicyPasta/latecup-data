"""Build data/nta2020.json from NYC Open Data's 2020 Neighborhood Tabulation Areas.

usage: python tools/build_nta.py [path to a downloaded GeoJSON]

Source: https://data.cityofnewyork.us/d/9nt8-h7nd (NYC Department of City
Planning, public domain). Rings are simplified to about 5 m, which is far
finer than a shopfront needs, and the file drops from 4.6 MB to well under 1 MB.
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from latecup_data import USER_AGENT  # noqa: E402

URL = "https://data.cityofnewyork.us/resource/9nt8-h7nd.geojson?$limit=1000"
TOL = 0.00005  # degrees, about 5 m


def _dp(points, tol):
    """Douglas-Peucker, iterative."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        best, idx = 0.0, None
        for i in range(a + 1, b):
            px, py = points[i]
            if norm == 0:
                dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                dist = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if dist > best:
                best, idx = dist, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(points, keep) if k]


def main():
    if len(sys.argv) > 1:
        raw = json.load(open(sys.argv[1]))
    else:
        raw = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=120).json()
    out = []
    for f in raw["features"]:
        p = f["properties"]
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        rings_out = []
        for poly in polys:
            rings = []
            for ring in poly:
                half = len(ring) // 2
                # simplify the two halves separately so a closed ring keeps its shape
                pts = _dp(ring[: half + 1], TOL)[:-1] + _dp(ring[half:], TOL)
                pts = [[round(x, 5), round(y, 5)] for x, y in pts]
                if len(pts) >= 4:
                    rings.append(pts)
            if rings:
                rings_out.append(rings)
        out.append({"code": p["nta2020"], "name": p["ntaname"], "boro": p["boroname"],
                    "type": p["ntatype"], "polys": rings_out})
    out.sort(key=lambda a: a["code"])
    dest = Path(__file__).resolve().parents[1] / "data" / "nta2020.json"
    dest.write_text(json.dumps({"source": "NYC Department of City Planning, 2020 Neighborhood Tabulation Areas "
                                          "(NYC Open Data 9nt8-h7nd), public domain; simplified to ~5 m",
                                "areas": out}, separators=(",", ":")))
    print(len(out), "areas,", dest.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
