"""Neighbourhood and borough for a point.

Polygons: NYC's 2020 Neighborhood Tabulation Areas (public domain), built by
tools/build_nta.py into data/nta2020.json. Names: the official NTA name made
friendly (see `friendly`), with a few small well-known areas the NTAs do not
separate (`SUB_AREAS`) checked first.
"""
import json
import math
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "nta2020.json"

# NTA name -> the name people use. Anything not listed gets the default rule:
# drop "(North)" style suffixes and keep the first part of a hyphenated name.
FRIENDLY = {
    # Manhattan
    "Chelsea-Hudson Yards": "Chelsea",
    "Chinatown-Two Bridges": "Chinatown",
    "East Midtown-Turtle Bay": "Midtown East",
    "Financial District-Battery Park City": "Financial District",
    "Hamilton Heights-Sugar Hill": "Hamilton Heights",
    "Manhattanville-West Harlem": "West Harlem",
    "Midtown South-Flatiron-Union Square": "Flatiron",
    "Midtown-Times Square": "Midtown",
    "Murray Hill-Kips Bay": "Murray Hill",
    "SoHo-Little Italy-Hudson Square": "SoHo",
    "Stuyvesant Town-Peter Cooper Village": "Stuyvesant Town",
    "The Battery-Governors Island-Ellis Island-Liberty Island": "The Battery",
    "Tribeca-Civic Center": "Tribeca",
    "Upper East Side-Carnegie Hill": "Upper East Side",
    "Upper East Side-Lenox Hill-Roosevelt Island": "Upper East Side",
    "Upper East Side-Yorkville": "Yorkville",
    "Upper West Side (Central)": "Upper West Side",
    "Upper West Side-Lincoln Square": "Lincoln Square",
    "Upper West Side-Manhattan Valley": "Manhattan Valley",
    "East Harlem (North)": "East Harlem",
    "East Harlem (South)": "East Harlem",
    "Harlem (North)": "Harlem",
    "Harlem (South)": "Harlem",
    "Washington Heights (North)": "Washington Heights",
    "Washington Heights (South)": "Washington Heights",
    # Brooklyn
    "Downtown Brooklyn-DUMBO-Boerum Hill": "Downtown Brooklyn",
    "Carroll Gardens-Cobble Hill-Gowanus-Red Hook": "Carroll Gardens",
    "Sunset Park (East)-Borough Park (West)": "Sunset Park",
    "Sunset Park (West)": "Sunset Park",
    "Sunset Park (Central)": "Sunset Park",
    "Bensonhurst": "Bensonhurst",
    "Gravesend (East)-Homecrest": "Gravesend",
    "Gravesend (South)": "Gravesend",
    "Gravesend (West)": "Gravesend",
    "Sheepshead Bay-Manhattan Beach-Gerritsen Beach": "Sheepshead Bay",
    "Coney Island-Sea Gate": "Coney Island",
    "Flatbush (West)-Ditmas Park-Parkville": "Ditmas Park",
    "Prospect Lefferts Gardens-Wingate": "Prospect Lefferts Gardens",
    "Crown Heights (North)": "Crown Heights",
    "Crown Heights (South)": "Crown Heights",
    "Bedford-Stuyvesant (East)": "Bedford-Stuyvesant",
    "Bedford-Stuyvesant (West)": "Bedford-Stuyvesant",
    "Bushwick (East)": "Bushwick",
    "Bushwick (West)": "Bushwick",
    "South Williamsburg": "Williamsburg",
    "East Williamsburg": "East Williamsburg",
    "Madison": "Madison",
    "Marine Park-Mill Basin-Bergen Beach": "Marine Park",
    "East New York (North)": "East New York",
    "East New York-City Line": "East New York",
    "East New York-New Lots": "East New York",
    "Spring Creek-Starrett City": "Starrett City",
    "Kensington": "Kensington",
    "Windsor Terrace-South Slope": "Windsor Terrace",
    "Dyker Heights": "Dyker Heights",
    "Bath Beach": "Bath Beach",
    "Mapleton-Midwood (West)": "Midwood",
    # Queens
    "Astoria (North)-Ditmars-Steinway": "Ditmars",
    "Astoria (Central)": "Astoria",
    "Astoria (East)-Woodside (North)": "Astoria",
    "Old Astoria-Hallets Point": "Astoria",
    "Queensbridge-Ravenswood-Dutch Kills": "Dutch Kills",
    "Long Island City-Hunters Point": "Long Island City",
    "Sunnyside Yards (North)": "Sunnyside",
    "Sunnyside Yards (South)": "Sunnyside",
    "Flushing-Willets Point": "Flushing",
    "East Flushing": "East Flushing",
    "Murray Hill-Broadway Flushing": "Murray Hill (Queens)",
    "Elmhurst": "Elmhurst",
    "Corona": "Corona",
    "North Corona": "Corona",
    "Jackson Heights": "Jackson Heights",
    "Rego Park": "Rego Park",
    "Forest Hills": "Forest Hills",
    "Bayside": "Bayside",
    "Oakland Gardens-Hollis Hills": "Oakland Gardens",
    "Douglaston-Little Neck": "Douglaston",
    "Jamaica Estates-Holliswood": "Jamaica Estates",
    "Jamaica Hills-Briarwood": "Briarwood",
    "Kew Gardens Hills": "Kew Gardens Hills",
    "Pomonok-Electchester-Hillcrest": "Hillcrest",
    "Fresh Meadows-Utopia": "Fresh Meadows",
    "Auburndale": "Auburndale",
    "Whitestone-Beechhurst": "Whitestone",
    "Bay Terrace-Clearview": "Bay Terrace",
    "John F. Kennedy International Airport": "JFK Airport",
    "Flushing Meadows-Corona Park": "Flushing Meadows",
    "Glen Oaks-Floral Park-New Hyde Park": "Glen Oaks",
    "Howard Beach-Lindenwood": "Howard Beach",
    "Ozone Park (North)": "Ozone Park",
    "South Ozone Park": "South Ozone Park",
    "Springfield Gardens (North)-Rochdale Village": "Springfield Gardens",
    "Springfield Gardens (South)-Brookville": "Springfield Gardens",
    "Breezy Point-Belle Harbor-Rockaway Park-Broad Channel": "Rockaway Park",
    "Rockaway Beach-Arverne-Edgemere": "Rockaway Beach",
    "Far Rockaway-Bayswater": "Far Rockaway",
    # The Bronx
    "Mott Haven-Port Morris": "Mott Haven",
    "Melrose": "Melrose",
    "Concourse-Concourse Village": "Concourse",
    "Mount Eden-Claremont (West)": "Mount Eden",
    "University Heights (North)-Fordham": "Fordham",
    "University Heights (South)-Morris Heights": "University Heights",
    "Kingsbridge-Marble Hill": "Kingsbridge",
    "Kingsbridge Heights-Van Cortlandt Village": "Kingsbridge Heights",
    "Riverdale-Spuyten Duyvil": "Riverdale",
    "Bedford Park": "Bedford Park",
    "Belmont": "Belmont",
    "Pelham Bay-Country Club-City Island": "Pelham Bay",
    "Throgs Neck-Schuylerville": "Throgs Neck",
    "Soundview-Bruckner-Bronx River": "Soundview",
    "Soundview-Clason Point": "Soundview",
    "Westchester Square": "Westchester Square",
    "Morris Park": "Morris Park",
    "Pelham Parkway-Van Nest": "Pelham Parkway",
    "Wakefield-Woodlawn": "Wakefield",
    "Co-op City": "Co-op City",
    # Staten Island
    "St. George-New Brighton": "St. George",
    "Tompkinsville-Stapleton-Clifton-Fox Hills": "Stapleton",
    "West New Brighton-Silver Lake-Grymes Hill": "West Brighton",
    "New Springville-Willowbrook-Bulls Head-Travis": "New Springville",
    "New Dorp-Midland Beach": "New Dorp",
    "Great Kills-Eltingville": "Great Kills",
    "Tottenville-Charleston": "Tottenville",
    "Annadale-Huguenot-Prince's Bay-Woodrow": "Annadale",
    "Arden Heights-Rossville": "Arden Heights",
    "Oakwood-Richmondtown": "Oakwood",
    "Todt Hill-Emerson Hill-Lighthouse Hill-Manor Heights": "Todt Hill",
    "Grasmere-Arrochar-South Beach-Dongan Hills": "Dongan Hills",
    "Rosebank-Shore Acres-Park Hill": "Rosebank",
    "Westerleigh-Castleton Corners": "Westerleigh",
    "Port Richmond": "Port Richmond",
    "Mariner's Harbor-Arlington-Graniteville": "Mariners Harbor",
}

# Areas nobody lives in whose name is still the right answer for a café inside them.
KEEP_NON_RESIDENTIAL = {
    "Central Park", "Prospect Park", "Flushing Meadows-Corona Park", "John F. Kennedy International Airport",
    "LaGuardia Airport", "The Battery-Governors Island-Ellis Island-Liberty Island", "United Nations",
    "Randall's Island", "Brooklyn Navy Yard"
}

# Small, well-known areas inside a larger NTA: name, (south, west, north, east).
# Rough rectangles; checked before the NTA name.
SUB_AREAS = [
    ("Koreatown", (40.7462, -73.9893, 40.7492, -73.9840)),
    ("NoMad", (40.7425, -73.9905, 40.7462, -73.9835)),
    ("Union Square", (40.7335, -73.9930, 40.7375, -73.9880)),
    ("Times Square", (40.7545, -73.9895, 40.7610, -73.9820)),
    ("Hudson Yards", (40.7510, -74.0080, 40.7580, -73.9985)),
    ("Little Italy", (40.7175, -73.9990, 40.7215, -73.9955)),
    ("Nolita", (40.7215, -73.9980, 40.7250, -73.9935)),
    ("NoHo", (40.7250, -73.9965, 40.7300, -73.9915)),
    ("DUMBO", (40.7005, -73.9930, 40.7050, -73.9830)),
    ("Battery Park City", (40.7050, -74.0200, 40.7180, -74.0135)),
    ("Kips Bay", (40.7385, -73.9830, 40.7445, -73.9710)),
    ("Cobble Hill", (40.6850, -74.0010, 40.6905, -73.9905)),
    ("Boerum Hill", (40.6830, -73.9905, 40.6890, -73.9800)),
    ("Red Hook", (40.6690, -74.0200, 40.6800, -74.0030)),
    ("Gowanus", (40.6690, -73.9960, 40.6800, -73.9840)),
]


def friendly(name):
    if name in FRIENDLY:
        return FRIENDLY[name]
    name = re.sub(r"\s*\((North|South|East|West|Central)\)", "", name)
    return name.split("-")[0].strip() if "-" in name and name not in ("Bedford-Stuyvesant",) else name


@lru_cache(maxsize=1)
def _areas():
    areas = json.loads(DATA.read_text())["areas"]
    for a in areas:
        xs = [x for poly in a["polys"] for x, _y in poly[0]]
        ys = [y for poly in a["polys"] for _x, y in poly[0]]
        a["bbox"] = (min(xs), min(ys), max(xs), max(ys))
    return areas


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_area(x, y, a):
    w, s, e, n = a["bbox"]
    if not (w <= x <= e and s <= y <= n):
        return False
    for poly in a["polys"]:
        if _in_ring(x, y, poly[0]) and not any(_in_ring(x, y, hole) for hole in poly[1:]):
            return True
    return False


def _dist_m(lat, lon, x, y):
    return math.hypot((x - lon) * 84400, (y - lat) * 111200)


def _nearest(lat, lon, residential=False, reach=0.02):
    """(metres, area) of the area with the closest boundary vertex, or None."""
    best = None
    for a in _areas():
        if residential and a["type"] != "0":
            continue
        w, s, e, n = a["bbox"]
        if not (w - reach <= lon <= e + reach and s - reach <= lat <= n + reach):
            continue
        for poly in a["polys"]:
            for x, y in poly[0]:
                d = _dist_m(lat, lon, x, y)
                if best is None or d < best[0]:
                    best = (d, a)
    return best


def locate(lat, lon, max_m=250):
    """(hood, boro, nta_code) or None when the point is not in New York City.

    A point just outside every polygon (a pier, a shoreline rounding) takes the
    nearest area within `max_m` metres.
    """
    hit = None
    for a in _areas():
        if _in_area(lon, lat, a):
            hit = a
            break
    if hit is None:
        best = _nearest(lat, lon)
        if best is None or best[0] > max_m:
            return None
        hit = best[1]
    if hit["type"] != "0" and hit["name"] not in KEEP_NON_RESIDENTIAL:
        # a cemetery, a small park, a rail yard: use the nearest neighbourhood people live in
        near = _nearest(lat, lon, residential=True)
        if near is not None:
            hit = near[1]
    hood = friendly(hit["name"])
    for name, (s, w, n, e) in SUB_AREAS:
        if s <= lat <= n and w <= lon <= e:
            hood = name
            break
    return hood, hit["boro"], hit["code"]
