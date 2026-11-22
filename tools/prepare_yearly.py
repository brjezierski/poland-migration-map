#!/usr/bin/env python3
"""Build data/yearly.json: immigration into other European countries with Poland as the country of
previous residence, by receiving country and year (Eurostat migr_imm5prv, partner PL); gaps are left as gaps.
Eurostat JSON-stat 2.0 API, no key needed.
"""
import argparse
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
UA = {"User-Agent": "poland-migration-map/1.0"}


def fetch(cache, name, query, cache_name=None):
    f = cache / f"{cache_name or name}.json"
    if not f.exists():
        f.write_bytes(urllib.request.urlopen(urllib.request.Request(f"{BASE}/{name}?format=JSON&lang=EN&{query}", headers=UA), timeout=120).read())
    return json.loads(f.read_text("utf-8"))


class Cube:
    """Minimal JSON-stat reader: value lookup by {dimension: category code}."""

    def __init__(self, j):
        self.j, self.ids, self.size = j, j["id"], j["size"]
        self.stride, s = {}, 1
        for d, n in reversed(list(zip(self.ids, self.size))):
            self.stride[d] = s
            s *= n
        self.idx = {d: j["dimension"][d]["category"]["index"] for d in self.ids}
        self.label = {d: j["dimension"][d]["category"].get("label", {}) for d in self.ids}

    def get(self, **pos):
        i = 0
        for d in self.ids:
            i += self.idx[d][pos[d]] * self.stride[d] if d in pos else 0
        v = self.j["value"].get(str(i))
        return None if v is None else int(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", default=str(ROOT / "data" / "yearly.json"))
    a = ap.parse_args()
    cache = pathlib.Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)

    # immigration into other European countries with Poland as the country of previous residence
    c4 = Cube(fetch(cache, "migr_imm5prv", "partner=PL&age=TOTAL&sex=T&agedef=COMPLET", cache_name="from_pl"))
    from_pl = {}
    for g in c4.idx["geo"]:
        row = {y: c4.get(geo=g, time=y) for y in sorted(c4.idx["time"])}
        row = {y: v for y, v in row.items() if v is not None}
        if row and g != "PL":
            from_pl[g] = row

    out = {"from_pl": from_pl}
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {a.out}: {len(from_pl)} receiving countries")
