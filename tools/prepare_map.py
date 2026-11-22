#!/usr/bin/env python3
"""Build data/map.json: simplified world country outlines as SVG path strings.

Input: Natural Earth 110m admin-0 countries GeoJSON (public domain), passed with --src.
Projection: Natural Earth (Savric), scaled to a 1000-unit-wide canvas. Antarctica is dropped.
Each country also gets an anchor point (centroid of its largest polygon) for flow arcs.
Crimea is drawn as part of Ukraine (it is a separate polygon, so Ukraine's anchor does not move).
"""
import argparse
import json
import math
import pathlib

from shapely.geometry import MultiPolygon, box, mapping, shape
from shapely.ops import unary_union  # noqa: F401  (kept for clarity of intent)

WIDTH = 1000.0
TOLERANCE = 0.35  # in projected units, after scaling


def project(lon, lat):
    lam, phi = math.radians(lon), math.radians(lat)
    p2, p4 = phi * phi, phi ** 4
    x = lam * (0.8707 - 0.131979 * p2 + p4 * (-0.013791 + p4 * (0.003971 * p2 - 0.001529 * p4)))
    y = phi * (1.007226 + p2 * (0.015085 + p4 * (-0.044475 + 0.028874 * p2 - 0.005916 * p4)))
    return x, y


def crimea_to_ukraine(gj):
    """Natural Earth's default outlines draw Crimea as Russian; move that polygon to Ukraine."""
    feats = {f["properties"]["ADM0_A3"]: f for f in gj["features"]}
    rus, ukr = shape(feats["RUS"]["geometry"]), shape(feats["UKR"]["geometry"])
    rus_parts = list(rus.geoms) if rus.geom_type == "MultiPolygon" else [rus]
    ukr_parts = list(ukr.geoms) if ukr.geom_type == "MultiPolygon" else [ukr]
    window = box(32.0, 44.0, 37.0, 46.5)  # the peninsula, west of the Kerch Strait
    crimea = [q for q in rus_parts if window.contains(q.representative_point())]
    assert len(crimea) == 1, "expected one Crimea polygon inside the Russian outline"
    feats["RUS"]["geometry"] = mapping(MultiPolygon([q for q in rus_parts if q is not crimea[0]]))
    feats["UKR"]["geometry"] = mapping(MultiPolygon(ukr_parts + crimea))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "data" / "map.json"))
    a = ap.parse_args()

    gj = json.loads(pathlib.Path(a.src).read_text(encoding="utf-8"))
    crimea_to_ukraine(gj)
    x_edge, _ = project(180, 0)
    scale = WIDTH / (2 * x_edge)
    _, y_top = project(0, 83.6)
    _, y_bot = project(0, -56)

    def proj_ring(coords):
        out = []
        for lon, lat in coords:
            x, y = project(lon, lat)
            out.append((x * scale + WIDTH / 2, -y * scale))
        return out

    def proj_poly(g):
        from shapely.geometry import Polygon
        ext = proj_ring(g.exterior.coords)
        holes = [proj_ring(r.coords) for r in g.interiors]
        return Polygon(ext, holes)

    countries, seen, raw = [], set(), {}
    y_min = -y_top * scale
    y_max = -y_bot * scale
    for f in gj["features"]:
        p = f["properties"]
        iso = p["ADM0_A3"]
        if iso == "ATA" or iso in seen:
            continue
        seen.add(iso)
        g = shape(f["geometry"])
        raw[iso] = g
        polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        pp = [proj_poly(q) for q in polys]
        pp = [q.simplify(TOLERANCE, preserve_topology=True) for q in pp]
        pp = [q for q in pp if not q.is_empty and q.area > 0.15]
        if not pp:
            continue
        big = max(pp, key=lambda q: q.area)
        parts = []
        for q in pp:
            for ring in [q.exterior] + list(q.interiors):
                pts = list(ring.coords)
                parts.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z")
        countries.append({
            "id": iso,
            "name": p["NAME"],
            "n3": int(p["ISO_N3_EH"]) if str(p["ISO_N3_EH"]).lstrip("-").isdigit() and int(p["ISO_N3_EH"]) > 0 else None,
            "a2": p["ISO_A2_EH"] if len(str(p["ISO_A2_EH"])) == 2 and str(p["ISO_A2_EH"]).isalpha() else None,
            "d": "".join(parts),
            "c": [round(big.centroid.x, 1), round(big.centroid.y, 1)],
        })

    # Borders of 1945-1989 for eastern Europe: the Soviet Union, Czechoslovakia and Yugoslavia as single
    # states, and Germany split along the inner German border. Poland's own borders are unchanged since 1945.
    def to_path(g):
        polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        pp = [proj_poly(q).simplify(TOLERANCE, preserve_topology=True) for q in polys]
        pp = [q for q in pp if not q.is_empty and q.area > 0.15]
        big = max(pp, key=lambda q: q.area)
        d = "".join("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in ring.coords) + "Z"
                    for q in pp for ring in [q.exterior] + list(q.interiors))
        return d, [round(big.centroid.x, 1), round(big.centroid.y, 1)]

    def merged(ids_):
        g = unary_union([raw[i] for i in ids_]).buffer(0.03).buffer(-0.03)  # close hairline seams between neighbours
        return g

    from shapely.geometry import Polygon as LLPoly
    # inner German border (lon, lat), Baltic coast to the Czech tripoint; GDR lies east of it
    border = [(10.95, 54.2), (10.87, 53.99), (10.75, 53.6), (10.6, 53.37), (11.25, 53.14), (11.55, 53.0), (10.9, 52.7),
              (10.9, 52.45), (10.6, 51.8), (10.2, 51.4), (10.0, 50.95), (10.0, 50.6), (10.95, 50.3), (12.2, 50.2),
              (12.2, 49.0), (25, 49.0), (25, 56), (10.95, 56)]
    gdr = raw["DEU"].intersection(LLPoly(border))
    frg = raw["DEU"].difference(gdr)
    groups = [
        ("SUN", "Soviet Union", merged("RUS UKR BLR EST LVA LTU MDA GEO ARM AZE KAZ UZB TKM KGZ TJK".split()),
         "RUS UKR BLR EST LVA LTU MDA GEO ARM AZE KAZ UZB TKM KGZ TJK".split()),
        ("CSK", "Czechoslovakia", merged(["CZE", "SVK"]), ["CZE", "SVK"]),
        ("YUG", "Yugoslavia", merged("SVN HRV BIH SRB MNE MKD KOS".split()), "SVN HRV BIH SRB MNE MKD KOS".split()),
        ("DDR", "East Germany", gdr, []),
        ("FRG", "West Germany", frg, ["DEU"]),
    ]
    old = []
    for oid, name, g, rep in groups:
        d, c = to_path(g)
        old.append({"id": oid, "name": name, "d": d, "c": c, "replaces": rep})
    # the modern Germany outline is hidden once and replaced by two shapes, so DDR carries it too
    old[3]["replaces"] = ["DEU"]
    old[4]["replaces"] = ["DEU"]

    ids = {c["id"] for c in countries}
    assert all(i in ids for o in old for i in o["replaces"]), "historical group uses an unknown country"
    assert "POL" in ids, "Poland missing from the map"
    out = {
        "w": WIDTH,
        "y0": round(y_min - 8, 1),
        "h": round(y_max - y_min + 16, 1),
        "countries": countries,
        "old": old,
    }
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = pathlib.Path(a.out).stat().st_size / 1024
    print(f"wrote {a.out}: {len(countries)} countries, {size:.0f} KiB, view {out['w']} x {out['h']} from y={out['y0']}")


if __name__ == "__main__":
    main()
