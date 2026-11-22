#!/usr/bin/env python3
"""Inline the map and flow data into index.template.html -> index.html.

The data is embedded so index.html opens straight from disk with no network access.
"""
import json
import pathlib

root = pathlib.Path(__file__).resolve().parent
amap = json.loads((root / "data" / "map.json").read_text(encoding="utf-8"))
flows = json.loads((root / "data" / "flows.json").read_text(encoding="utf-8"))

# Every flow must point at a country or a historical state that exists on the map.
ids = {c["id"] for c in amap["countries"]} | {c["id"] for c in amap["old"]}  # old: states of the time
assert "POL" in ids
for f in flows["flows"]:
    assert f["c"] in ids, f"flow country {f['c']} has no map shape"
    assert min(f["in"], f["out"]) >= 0 and (f["in"] or f["out"]), f"bad flow {f}"
    assert 0 <= f["p"] < len(flows["periods"]), f"bad period index {f}"
    assert f["c"] in flows["countries"], f"{f['c']} missing from country names"

# Every drawn value needs a recorded basis, and every low confidence needs a reason.
for b_ in flows["bases"]:
    assert b_["c"] != "low" or b_.get("w"), f"low confidence without reason: {b_}"
for f in flows["flows"]:
    for k, v in (("in", f["in"]), ("out", f["out"])):
        assert not v or k in f["b"], f"{f['c']} period {f['p']} has {k} without a source"

tpl = (root / "index.template.html").read_text(encoding="utf-8")
assert "/*MAP*/null" in tpl and "/*FLOWS*/null" in tpl and "__ASPECT__" in tpl


def js(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


# Drop the unused anchors' siblings: the page only needs id, name, path and anchor point.
slim = {**amap, "countries": [{k: c[k] for k in ("id", "name", "d", "c")} for c in amap["countries"]]}
html = (tpl.replace("/*MAP*/null", js(slim))
        .replace("/*FLOWS*/null", js(flows))
        .replace("__ASPECT__", f"{amap['w']:.0f} / {amap['h']:.0f}"))
(root / "index.html").write_text(html, encoding="utf-8")
print(f"wrote index.html ({len(html) / 1024:.0f} KiB)")
