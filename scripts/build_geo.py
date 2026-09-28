#!/usr/bin/env python3
"""
Turn the raw Chicago Data Portal boundary downloads in data/raw/geo/ into
the slimmed-down GeoJSON layers the dashboard's map actually fetches
(docs/data/geo/*.geojson), and use those same boundaries to fill in any
gaps in docs/data/school_groups.json (Community Area / Network) for
schools the source Excel didn't cover, via a one-time point-in-polygon
join. Also writes docs/data/geo/schools_no_boundary.json -- the list of
enrolled schools with no matching attendance-boundary polygon (citywide /
selective-enrollment schools), for the "no boundary" table under the map.

This never talks to the network -- run fetch_geo.py first to populate
data/raw/geo/.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "geo"
GEO_OUT_DIR = REPO_ROOT / "docs" / "data" / "geo"
DATA_DIR = REPO_ROOT / "docs" / "data"


def load_raw(name):
    path = RAW_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def round_coords(coords, ndigits=5):
    if isinstance(coords[0], (int, float)):
        return [round(c, ndigits) for c in coords]
    return [round_coords(c, ndigits) for c in coords]


def clean_feature(geometry, properties):
    return {
        "type": "Feature",
        "geometry": {"type": geometry["type"], "coordinates": round_coords(geometry["coordinates"])},
        "properties": properties,
    }


def fc(features):
    return {"type": "FeatureCollection", "features": features}


# --------------------------------------------------------------------
# 1. Community Areas
# --------------------------------------------------------------------
def build_community_areas():
    raw = load_raw("cps_geo_community_areas")
    out = []
    for feat in raw["features"]:
        p = feat["properties"]
        name = str(p.get("community", "")).strip().upper()
        if not name:
            continue
        out.append(clean_feature(feat["geometry"], {
            "community_area": name,
            "area_num": int(float(p.get("area_num_1") or p.get("area_numbe") or 0)),
        }))
    path = GEO_OUT_DIR / "community_areas.geojson"
    with open(path, "w") as f:
        json.dump(fc(out), f)
    print(f"community_areas.geojson: {len(out)} features")
    return {f["properties"]["community_area"] for f in out}


# --------------------------------------------------------------------
# 2. Networks (elementary geo networks + high school geo networks share
#    the same "Network N" numbering, so they combine into one 1-17 layer)
# --------------------------------------------------------------------
def build_networks():
    seen = {}
    named = 0
    for name in ("cps_geo_networks_elementary", "cps_geo_networks_highschool"):
        raw = load_raw(name)
        for feat in raw["features"]:
            p = feat["properties"]
            net = str(p.get("network", "")).strip()
            if not net or net in seen:
                continue
            # Elementary networks (1-13) carry a "planningzo" geographic label
            # in CPS's own boundary file (e.g. "Logan-Lincoln Park"); high
            # school networks (14-17) don't have an equivalent, so this is
            # left out of the properties for those (front end falls back to
            # the plain "Network N" label when absent).
            props = {"network": net}
            zone = str(p.get("planningzo") or "").strip()
            if zone:
                props["network_name"] = zone
                named += 1
            seen[net] = clean_feature(feat["geometry"], props)
    path = GEO_OUT_DIR / "networks.geojson"
    with open(path, "w") as f:
        json.dump(fc(list(seen.values())), f)
    print(f"networks.geojson: {len(seen)} features ({named} with a geographic name)")
    return set(seen.keys())


# --------------------------------------------------------------------
# 3. School attendance boundaries -- elementary layer (ES + MS merged,
#    since both serve the "elementary" attendance system) and a separate
#    high school layer, each keyed by School ID.
# --------------------------------------------------------------------
def _school_name(p):
    return str(p.get("school_nam") or p.get("short_name") or p.get("school_add") or "").strip()


def build_attendance():
    covered_ids = set()

    def build_layer(out_name, raw_names):
        features = []
        for raw_name in raw_names:
            raw = load_raw(raw_name)
            for feat in raw["features"]:
                p = feat["properties"]
                sid = str(p.get("school_id", "")).strip()
                if not sid:
                    continue
                covered_ids.add(sid)
                features.append(clean_feature(feat["geometry"], {
                    "school_id": sid,
                    "school_name": _school_name(p),
                }))
        path = GEO_OUT_DIR / f"{out_name}.geojson"
        with open(path, "w") as f:
            json.dump(fc(features), f)
        print(f"{out_name}.geojson: {len(features)} features")

    build_layer("attendance_elementary", ["cps_geo_attendance_elementary", "cps_geo_attendance_middle"])
    build_layer("attendance_highschool", ["cps_geo_attendance_highschool"])
    return covered_ids


# --------------------------------------------------------------------
# Point-in-polygon (even-odd rule, handles holes/MultiPolygon correctly)
# --------------------------------------------------------------------
def _ray_cast(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def _point_in_polygon_rings(x, y, rings):
    return sum(1 for ring in rings if _ray_cast(x, y, ring)) % 2 == 1


def _point_in_feature(x, y, geometry):
    if geometry["type"] == "Polygon":
        return _point_in_polygon_rings(x, y, geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return any(_point_in_polygon_rings(x, y, poly) for poly in geometry["coordinates"])
    return False


def find_containing(lon, lat, features, prop_key):
    for feat in features:
        if _point_in_feature(lon, lat, feat["geometry"]):
            return feat["properties"][prop_key]
    return None


# --------------------------------------------------------------------
# 4. Fill gaps in school_groups.json via point-in-polygon, for schools
#    the Excel source didn't cover (or covered with a null community
#    area / non-geographic network value).
# --------------------------------------------------------------------
def fill_group_gaps():
    with open(DATA_DIR / "school_locations.json") as f:
        locs = json.load(f)
    groups_path = DATA_DIR / "school_groups.json"
    with open(groups_path) as f:
        groups = json.load(f)

    ca_raw = load_raw("cps_geo_community_areas")
    ca_features = [clean_feature(f["geometry"], {"community_area": str(f["properties"].get("community", "")).strip().upper()})
                   for f in ca_raw["features"] if f["properties"].get("community")]

    net_seen = {}
    for name in ("cps_geo_networks_elementary", "cps_geo_networks_highschool"):
        for feat in load_raw(name)["features"]:
            net = str(feat["properties"].get("network", "")).strip()
            if net and net not in net_seen:
                net_seen[net] = clean_feature(feat["geometry"], {"network": net})
    net_features = list(net_seen.values())

    filled_ca = filled_net = 0
    for sid, (lat, lon) in locs.items():
        entry = groups.get(sid) or {"network": None, "community_area": None}
        if not entry.get("community_area"):
            found = find_containing(lon, lat, ca_features, "community_area")
            if found:
                entry["community_area"] = found
                filled_ca += 1
        if not entry.get("network"):
            found = find_containing(lon, lat, net_features, "network")
            if found:
                entry["network"] = found
                filled_net += 1
        groups[sid] = entry

    with open(groups_path, "w") as f:
        json.dump(groups, f)
    print(f"school_groups.json: filled {filled_ca} missing community areas, {filled_net} missing networks (via point-in-polygon)")


# --------------------------------------------------------------------
# 5. Schools with no attendance-boundary match (citywide / selective-
#    enrollment schools) -- listed in a table instead of drawn as a
#    boundary on the map.
# --------------------------------------------------------------------
def build_no_boundary_list(covered_ids):
    with open(DATA_DIR / "schools.json") as f:
        schools_data = json.load(f)
    latest_year = schools_data["years"][-1]
    latest_rows = [r for r in schools_data["schools"] if r["year"] == latest_year and r["total"] > 0]

    no_boundary = []
    seen_ids = set()
    for r in latest_rows:
        sid = str(r["school_id"])
        if sid in seen_ids or sid in covered_ids:
            continue
        seen_ids.add(sid)
        no_boundary.append({"school_id": sid, "school_name": r["school_name"], "total": r["total"]})
    no_boundary.sort(key=lambda r: r["school_name"])

    path = GEO_OUT_DIR / "schools_no_boundary.json"
    with open(path, "w") as f:
        json.dump({"year": latest_year, "schools": no_boundary}, f)
    print(f"schools_no_boundary.json: {len(no_boundary)} schools with no attendance boundary (of {len(latest_rows)} enrolled in {latest_year})")


def main():
    GEO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_community_areas()
    build_networks()
    covered_ids = build_attendance()
    fill_group_gaps()
    build_no_boundary_list(covered_ids)


if __name__ == "__main__":
    main()
