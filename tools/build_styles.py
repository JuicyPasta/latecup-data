"""Write styles/style-dark.json and styles/style-light.json.

MapLibre styles for the OpenMapTiles schema on OpenFreeMap's free vector
tiles (https://openfreemap.org). One layer list, two palettes. No sprite and
no POI icons: Latecup's own pins are the content. Dark is the main one.

usage: python tools/build_styles.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TILES = "https://tiles.openfreemap.org/planet"
GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
ATTRIBUTION = ('<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> '
               '<a href="https://www.openmaptiles.org/" target="_blank">&copy; OpenMapTiles</a> '
               'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>')

DARK = {
    "name": "Latecup Dark",
    "land": "#0E1116", "water": "#0A1823", "park": "#111A18", "building": "#131821", "building_line": "#171D27",
    "pier": "#10141A", "aeroway": "#151A22",
    "road_minor": "#1B212B", "road_major": "#262E3A", "road_motorway": "#2D3644", "road_casing": "#0B0E12",
    "path": "#1A2029", "rail": "#1F2630", "boundary": "#2A323D",
    "label_street": "#8690A0", "label_street_major": "#9AA5B4", "label_hood": "#A9B3C1", "label_city": "#C9D1DB",
    "label_water": "#3F5A72", "label_park": "#4C6659", "label_station": "#6E7A8A", "station_dot": "#566170",
    "halo": "#0E1116", "halo_width": 1.4,
}
LIGHT = {
    "name": "Latecup Light",
    "land": "#F5F2EC", "water": "#C9DAE6", "park": "#DCE8D3", "building": "#ECE8E0", "building_line": "#E2DDD3",
    "pier": "#EFECE5", "aeroway": "#E9E5DD",
    "road_minor": "#FFFFFF", "road_major": "#FFFFFF", "road_motorway": "#FBE9C4", "road_casing": "#DDD7CC",
    "path": "#E6E0D5", "rail": "#D2CCC0", "boundary": "#B9B2A6",
    "label_street": "#6B7380", "label_street_major": "#555E6B", "label_hood": "#4A5360", "label_city": "#2B323C",
    "label_water": "#6E93AD", "label_park": "#5E8A5F", "label_station": "#6B7380", "station_dot": "#8A93A0",
    "halo": "#F5F2EC", "halo_width": 1.6,
}

MINOR = ["minor", "service", "track"]
MAJOR = ["primary", "secondary", "tertiary", "trunk"]


def width(pairs):
    """An exponential zoom ramp from (zoom, width) pairs."""
    return ["interpolate", ["exponential", 1.5], ["zoom"], *[v for pair in pairs for v in pair]]


def layers(c):
    road_filter = lambda classes: ["all", ["==", ["geometry-type"], "LineString"],  # noqa: E731
                                   ["match", ["get", "class"], classes, True, False],
                                   ["!=", ["get", "brunnel"], "tunnel"]]
    tunnel_filter = lambda classes: ["all", ["==", ["geometry-type"], "LineString"],  # noqa: E731
                                     ["match", ["get", "class"], classes, True, False],
                                     ["==", ["get", "brunnel"], "tunnel"]]
    round_line = {"line-cap": "round", "line-join": "round"}
    name = ["coalesce", ["get", "name:en"], ["get", "name:latin"], ["get", "name"]]
    out = [
        {"id": "background", "type": "background", "paint": {"background-color": c["land"]}},
        {"id": "park", "type": "fill", "source": "openmaptiles", "source-layer": "park",
         "paint": {"fill-color": c["park"]}},
        {"id": "landcover_green", "type": "fill", "source": "openmaptiles", "source-layer": "landcover",
         "filter": ["match", ["get", "class"], ["grass", "wood"], True, False],
         "paint": {"fill-color": c["park"], "fill-opacity": 0.8}},
        {"id": "landuse_green", "type": "fill", "source": "openmaptiles", "source-layer": "landuse",
         "filter": ["match", ["get", "class"], ["cemetery", "pitch", "stadium", "playground"], True, False],
         "paint": {"fill-color": c["park"], "fill-opacity": 0.7}},
        {"id": "water", "type": "fill", "source": "openmaptiles", "source-layer": "water",
         "filter": ["!=", ["get", "brunnel"], "tunnel"],
         "paint": {"fill-color": c["water"]}},
        {"id": "waterway", "type": "line", "source": "openmaptiles", "source-layer": "waterway",
         "paint": {"line-color": c["water"], "line-width": width([(10, 0.8), (16, 3)])}},
        {"id": "aeroway_area", "type": "fill", "source": "openmaptiles", "source-layer": "aeroway", "minzoom": 11,
         "filter": ["==", ["geometry-type"], "Polygon"],
         "paint": {"fill-color": c["aeroway"]}},
        {"id": "aeroway_line", "type": "line", "source": "openmaptiles", "source-layer": "aeroway", "minzoom": 11,
         "filter": ["==", ["geometry-type"], "LineString"],
         "paint": {"line-color": c["aeroway"], "line-width": width([(11, 1), (16, 12)])}},
        {"id": "pier_area", "type": "fill", "source": "openmaptiles", "source-layer": "transportation",
         "filter": ["all", ["==", ["geometry-type"], "Polygon"], ["==", ["get", "class"], "pier"]],
         "paint": {"fill-color": c["pier"]}},
        {"id": "pier_line", "type": "line", "source": "openmaptiles", "source-layer": "transportation",
         "filter": ["all", ["==", ["geometry-type"], "LineString"], ["==", ["get", "class"], "pier"]],
         "paint": {"line-color": c["pier"], "line-width": width([(13, 1), (17, 6)])}},
        {"id": "building", "type": "fill", "source": "openmaptiles", "source-layer": "building", "minzoom": 14,
         "paint": {"fill-color": c["building"], "fill-outline-color": c["building_line"],
                   "fill-opacity": ["interpolate", ["linear"], ["zoom"], 14, 0, 15.5, 1]}},
        {"id": "tunnel", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 12,
         "filter": tunnel_filter(MAJOR + ["motorway"]), "layout": round_line,
         "paint": {"line-color": c["road_minor"], "line-dasharray": [2, 2],
                   "line-width": width([(12, 0.6), (16, 4), (20, 18)])}},
        {"id": "path", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 15,
         "filter": ["all", ["==", ["geometry-type"], "LineString"], ["==", ["get", "class"], "path"]],
         "layout": round_line,
         "paint": {"line-color": c["path"], "line-dasharray": [2, 1.5], "line-width": width([(15, 0.7), (18, 2)])}},
        {"id": "rail", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 12,
         "filter": ["all", ["==", ["get", "class"], "rail"], ["!=", ["get", "brunnel"], "tunnel"]],
         "paint": {"line-color": c["rail"], "line-dasharray": [4, 2], "line-width": width([(12, 0.6), (17, 1.6)])}},
        {"id": "road_casing", "type": "line", "source": "openmaptiles", "source-layer": "transportation",
         "minzoom": 13, "filter": road_filter(MAJOR + ["motorway"] + MINOR), "layout": round_line,
         "paint": {"line-color": c["road_casing"],
                   "line-width": width([(13, 1.6), (16, 9), (20, 44)]),
                   "line-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 15, 1]}},
        {"id": "road_minor", "type": "line", "source": "openmaptiles", "source-layer": "transportation",
         "minzoom": 12, "filter": road_filter(MINOR), "layout": round_line,
         "paint": {"line-color": c["road_minor"], "line-width": width([(12, 0.4), (14, 1.4), (16, 5), (20, 34)])}},
        {"id": "road_major", "type": "line", "source": "openmaptiles", "source-layer": "transportation",
         "minzoom": 8, "filter": road_filter(MAJOR), "layout": round_line,
         "paint": {"line-color": c["road_major"],
                   "line-width": width([(8, 0.4), (12, 1.2), (14, 2.6), (16, 8), (20, 40)])}},
        {"id": "road_motorway", "type": "line", "source": "openmaptiles", "source-layer": "transportation",
         "minzoom": 6, "filter": road_filter(["motorway"]), "layout": round_line,
         "paint": {"line-color": c["road_motorway"],
                   "line-width": width([(6, 0.5), (12, 1.6), (14, 3), (16, 9), (20, 42)])}},
        {"id": "boundary_state", "type": "line", "source": "openmaptiles", "source-layer": "boundary",
         "filter": ["all", ["==", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]],
         "paint": {"line-color": c["boundary"], "line-dasharray": [3, 2], "line-width": 0.8}},
        # ------------------------------------------------------------- labels
        {"id": "label_water_line", "type": "symbol", "source": "openmaptiles", "source-layer": "water_name",
         "minzoom": 10, "filter": ["==", ["geometry-type"], "LineString"],
         "layout": {"text-field": name, "text-font": ["Noto Sans Italic"], "text-size": 12,
                    "text-letter-spacing": 0.08, "symbol-placement": "line"},
         "paint": {"text-color": c["label_water"], "text-halo-color": c["water"], "text-halo-width": 1}},
        {"id": "label_water_point", "type": "symbol", "source": "openmaptiles", "source-layer": "water_name",
         "minzoom": 10, "filter": ["==", ["geometry-type"], "Point"],
         "layout": {"text-field": name, "text-font": ["Noto Sans Italic"], "text-size": 12,
                    "text-max-width": 6, "text-letter-spacing": 0.08},
         "paint": {"text-color": c["label_water"], "text-halo-color": c["water"], "text-halo-width": 1}},
        {"id": "label_park", "type": "symbol", "source": "openmaptiles", "source-layer": "poi", "minzoom": 13.5,
         "filter": ["all", ["==", ["get", "class"], "park"], ["<=", ["get", "rank"], 8]],
         "layout": {"text-field": name, "text-font": ["Noto Sans Italic"], "text-size": 11, "text-max-width": 7,
                    "text-padding": 6},
         "paint": {"text-color": c["label_park"], "text-halo-color": c["halo"], "text-halo-width": c["halo_width"]}},
        {"id": "label_street_minor", "type": "symbol", "source": "openmaptiles",
         "source-layer": "transportation_name", "minzoom": 14.5,
         "filter": ["match", ["get", "class"], MINOR, True, False],
         "layout": {"symbol-placement": "line", "text-field": name, "text-font": ["Noto Sans Regular"],
                    "text-size": ["interpolate", ["linear"], ["zoom"], 14.5, 10, 18, 13],
                    "text-letter-spacing": 0.02, "symbol-spacing": 320, "text-max-angle": 30},
         "paint": {"text-color": c["label_street"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"]}},
        {"id": "label_street_major", "type": "symbol", "source": "openmaptiles",
         "source-layer": "transportation_name", "minzoom": 12.5,
         "filter": ["match", ["get", "class"], MAJOR + ["motorway"], True, False],
         "layout": {"symbol-placement": "line", "text-field": name, "text-font": ["Noto Sans Regular"],
                    "text-size": ["interpolate", ["linear"], ["zoom"], 12.5, 10, 18, 14],
                    "text-letter-spacing": 0.02, "symbol-spacing": 380, "text-max-angle": 30},
         "paint": {"text-color": c["label_street_major"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"]}},
        {"id": "station_dot", "type": "circle", "source": "openmaptiles", "source-layer": "poi", "minzoom": 14,
         "filter": ["all", ["==", ["get", "class"], "railway"],
                    ["match", ["get", "subclass"], ["station", "subway", "halt"], True, False]],
         "paint": {"circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 1.6, 17, 3.2],
                   "circle-color": c["station_dot"], "circle-stroke-color": c["halo"], "circle-stroke-width": 1}},
        {"id": "label_station", "type": "symbol", "source": "openmaptiles", "source-layer": "poi", "minzoom": 15,
         "filter": ["all", ["==", ["get", "class"], "railway"],
                    ["match", ["get", "subclass"], ["station", "subway", "halt"], True, False]],
         "layout": {"text-field": name, "text-font": ["Noto Sans Regular"], "text-size": 10.5,
                    "text-anchor": "top", "text-offset": [0, 0.5], "text-max-width": 7, "text-optional": True,
                    "text-padding": 4},
         "paint": {"text-color": c["label_station"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"]}},
        {"id": "label_neighbourhood", "type": "symbol", "source": "openmaptiles", "source-layer": "place",
         "minzoom": 11.5, "maxzoom": 16.5,
         "filter": ["match", ["get", "class"], ["neighbourhood", "quarter", "suburb"], True, False],
         "layout": {"text-field": name, "text-font": ["Noto Sans Bold"], "text-transform": "uppercase",
                    "text-letter-spacing": 0.12, "text-max-width": 7, "text-padding": 8,
                    "text-size": ["interpolate", ["linear"], ["zoom"], 11.5, 9.5, 15, 12.5],
                    "symbol-sort-key": ["get", "rank"]},
         "paint": {"text-color": c["label_hood"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"],
                   "text-opacity": ["interpolate", ["linear"], ["zoom"], 11.5, 0.75, 13, 1]}},
        {"id": "label_borough", "type": "symbol", "source": "openmaptiles", "source-layer": "place",
         "minzoom": 9, "maxzoom": 13,
         "filter": ["match", ["get", "class"], ["borough", "island"], True, False],
         "layout": {"text-field": name, "text-font": ["Noto Sans Bold"], "text-transform": "uppercase",
                    "text-letter-spacing": 0.16, "text-max-width": 8,
                    "text-size": ["interpolate", ["linear"], ["zoom"], 9, 11, 13, 15]},
         "paint": {"text-color": c["label_city"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"]}},
        {"id": "label_town", "type": "symbol", "source": "openmaptiles", "source-layer": "place",
         "minzoom": 8, "maxzoom": 14,
         "filter": ["match", ["get", "class"], ["town", "village"], True, False],
         "layout": {"text-field": name, "text-font": ["Noto Sans Regular"], "text-max-width": 8,
                    "text-size": ["interpolate", ["linear"], ["zoom"], 8, 10, 13, 13]},
         "paint": {"text-color": c["label_hood"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"]}},
        {"id": "label_city", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 12,
         "filter": ["==", ["get", "class"], "city"],
         "layout": {"text-field": name, "text-font": ["Noto Sans Bold"], "text-max-width": 8,
                    "text-size": ["interpolate", ["linear"], ["zoom"], 4, 11, 11, 18],
                    "symbol-sort-key": ["get", "rank"]},
         "paint": {"text-color": c["label_city"], "text-halo-color": c["halo"],
                   "text-halo-width": c["halo_width"]}},
    ]
    return out


def style(c):
    return {
        "version": 8,
        "name": c["name"],
        "metadata": {"latecup:about": "Made for Latecup by tools/build_styles.py in JuicyPasta/latecup-data. "
                                      "OpenMapTiles schema, OpenFreeMap tiles. No sprite: the app's pins are the content."},
        "sources": {"openmaptiles": {"type": "vector", "url": TILES, "attribution": ATTRIBUTION}},
        "glyphs": GLYPHS,
        "layers": layers(c),
    }


def main():
    for file, palette in (("style-dark.json", DARK), ("style-light.json", LIGHT)):
        path = ROOT / "styles" / file
        path.write_text(json.dumps(style(palette), separators=(",", ":"), ensure_ascii=False) + "\n")
        print(file, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
