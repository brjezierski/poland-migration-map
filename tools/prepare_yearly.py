#!/usr/bin/env python3
"""Build data/yearly.json: Poland's yearly immigration figures from Eurostat (Statistics Poland data).

Three series, kept separate because they measure different things:
- totals: immigration to Poland per year, 1998-2024 (migr_imm5prv, total partner). Poland
  reports country detail only for 2001-2007 (permanent residence), in the same table.
- prev: those 2001-2007 country-of-previous-residence counts.
- permits: first residence permits issued to non-EU citizens, by citizenship and validity,
  2008-2025 (migr_resfirst). These are permits, not arrivals.
- from_pl: immigration into other European countries with Poland as the country of previous
  residence, by receiving country and year (migr_imm5prv, partner PL); gaps are left as gaps.
- tp: people under temporary protection at the end of each December from 2022 (migr_asytpsm), a stock
  of people registered at that date, not arrivals.
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

    # totals and 2001-2007 previous residence
    c1 = Cube(fetch(cache, "migr_imm5prv", "geo=PL&age=TOTAL&sex=T&agedef=COMPLET"))
    years = sorted(c1.idx["time"])
    totals = {y: c1.get(partner="TOTAL", time=y) for y in years}
    totals = {y: v for y, v in totals.items() if v}
    prev, names = {}, {}
    for y in years:
        row = {}
        for p in c1.idx["partner"]:
            if len(p) == 2 and p != "EU":
                v = c1.get(partner=p, time=y)
                if v:
                    row[p] = v
                    names[p] = c1.label["partner"][p]
        if len(row) >= 10:  # a real country split; Eurostat has a lone UK value for 2019
            prev[y] = row

    # first residence permits
    c2 = Cube(fetch(cache, "migr_resfirst", "geo=PL&reason=TOTAL"))
    durations = {d: c2.label["duration"][d] for d in c2.idx["duration"]}
    permits = {}
    for y in sorted(c2.idx["time"]):
        by_dur = {}
        for d in durations:
            row = {}
            for c in c2.idx["citizen"]:
                if len(c) == 2 and c != "EU":
                    v = c2.get(citizen=c, duration=d, time=y)
                    if v:
                        row[c] = v
                        names[c] = c2.label["citizen"][c]
            tot = c2.get(citizen="TOTAL", duration=d, time=y)
            if tot:
                by_dur[d] = {"total": tot, "by": row}
        if by_dur:
            permits[y] = by_dur

    # temporary protection: people under protection at the end of the month (a stock, not arrivals)
    c3 = Cube(fetch(cache, "migr_asytpsm", "geo=PL&age=TOTAL&sex=T"))
    months = sorted(c3.idx["time"])

    def tp_at(m):
        by = {}
        for c in c3.idx["citizen"]:
            if len(c) == 2 and c != "EU":
                v = c3.get(citizen=c, time=m)
                if v:
                    by[c] = v
                    names[c] = c3.label["citizen"][c]
        return {"total": c3.get(citizen="TOTAL", time=m), "by": by}

    tp = {m[:4]: tp_at(m) for m in months if m.endswith("-12")}
    tp_latest = {"month": months[-1], **tp_at(months[-1])}

    # immigration into other European countries with Poland as the country of previous residence
    c4 = Cube(fetch(cache, "migr_imm5prv", "partner=PL&age=TOTAL&sex=T&agedef=COMPLET", cache_name="from_pl"))
    from_pl, geo_names = {}, {}
    for g in c4.idx["geo"]:
        row = {y: c4.get(geo=g, time=y) for y in sorted(c4.idx["time"])}
        row = {y: v for y, v in row.items() if v is not None}
        if row and g != "PL":
            from_pl[g] = row
            geo_names[g] = c4.label["geo"][g]
    names.update({k: v for k, v in geo_names.items() if k not in names})

    out = {"totals": totals, "prev": prev, "permits": permits, "durations": durations, "names": names,
           "tp": tp, "tp_latest": tp_latest, "from_pl": from_pl}
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {a.out}: totals {min(totals)}-{max(totals)}, country split {sorted(prev)[0]}-{sorted(prev)[-1]}, permits {min(permits)}-{max(permits)}")
    print("temporary protection, end of December:", {y: v["total"] for y, v in tp.items()}, "| latest", tp_latest["month"], tp_latest["total"])
    print("durations:", durations)
    for y in ("2008", "2017", "2024"):
        print(y, {d: permits[y][d]["total"] for d in permits[y]})
    # keep only the biggest citizenships per year and duration so the page stays small
    # (done in the page's build step, not here, so the data file stays complete)


if __name__ == "__main__":
    main()
