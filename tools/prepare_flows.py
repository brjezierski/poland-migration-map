#!/usr/bin/env python3
"""Build data/flows.json: migration to and from Poland per 5-year period, 1945-2024.

- 1945-1989: hand-curated rows from data/historical_1945_1989.json (approximate).
- 1990-2024: change in bilateral migrant stocks between the UN DESA reference years
  (International Migrant Stock 2024, Table 1, both sexes; 1990, 1995 ... 2020, 2024).
  For each partner country the growth of the stock of its people in Poland is 'in', and the
  growth of the stock of Poland-born people living there is 'out'. Shrinking stocks (deaths,
  returns, naturalisation, re-estimation) count as 0, so these are net stock growth, not
  gross flows. The last period is 2020-24, four years long.
"""
import argparse
import json
import re
import pathlib
import urllib.request

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
UN_URL = "https://www.un.org/development/desa/pd/sites/www.un.org.development.desa.pd/files/undesa_pd_2024_ims_stock_by_sex_destination_and_origin.xlsx"
FIRST, STEP = 1945, 5
STOCK_YEARS = [1990, 1995, 2000, 2005, 2010, 2015, 2020, 2024]  # columns of the first block of Table 1
NATIONAL_MIN = 100       # official yearly counts are kept down to this size
MIN_PEOPLE = 1000        # smaller stock changes are dropped from the page
KEEP_PER_DIRECTION = 30  # largest partners kept per direction and period (stock periods)
PSEUDO = {"SUN": "Soviet Union", "CSK": "Czechoslovakia", "YUG": "Yugoslavia"}  # states of the time, kept apart from their successors


W = "https://en.wikipedia.org/wiki/"
EUROSTAT = "https://ec.europa.eu/eurostat/databrowser/view/{}/default/table"
# (text found in a source string, page that holds the data); every matching rule adds a link
LINK_RULES = [
    ("UN DESA", "https://www.un.org/development/desa/pd/content/international-migrant-stock"),
    ("migr_imm5prv", EUROSTAT.format("migr_imm5prv")),
    ("migr_resfirst", EUROSTAT.format("migr_resfirst")),
    ("migr_asytpsm", EUROSTAT.format("migr_asytpsm")),
    ("International Passenger Survey", "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/internationalmigration/datasets/ipscountryofbirthbycountryoflastornextresidence"),
    ("Aussiedler", W + "Aussiedler"),
    ("Statistical Abstract of Israel", "https://www.cbs.gov.il/en/publications/Pages/2010/Statistical-Abstract-of-Israel-2010-No-61.aspx"),
    ("FNA10", "https://data.cso.ie/table/FNA10"),
    ("Department of Social Protection", "https://data.gov.ie/dataset/personal-public-service-number-ppsn-allocations"),
    ("Statistics Iceland", "https://px.hagstofa.is/pxen/pxweb/en/Ibuar/Ibuar__buferlaflutningar__buferlaflmillilanda/MAN01404.px"),
    ("Statistics Sweden", "https://www.statistikdatabasen.scb.se/pxweb/en/ssd/START__BE__BE0101__BE0101J/ImmiEmiFlyttN/"),
    ("Statistics Norway", "https://data.ssb.no/api/v0/en/table/07822"),
    ("Statistics Denmark", "https://www.statbank.dk/INDVAN"),
    ("migr_emi3nxt", "https://ec.europa.eu/eurostat/databrowser/view/migr_emi3nxt/default/table"),
    ("table 85671NED", "https://opendata.cbs.nl/#/CBS/nl/dataset/85671NED/table"),
    ("table 82350NED", "https://opendata.cbs.nl/#/CBS/nl/dataset/82350NED/table"),
    ("Statistics Finland", "https://pxdata.stat.fi/PxWeb/pxweb/en/StatFin/StatFin__muutl/statfin_muutl_pxt_159p.px"),
    ("ABS, Overseas Migration", "https://www.abs.gov.au/statistics/people/population/overseas-migration/2022-23-financial-year"),
    ("Australian census Poland-born", W + "Polish_Australians"),
    ("Historical Population Statistics", "https://www.abs.gov.au/statistics/people/population/historical-population/latest-release"),
    ("Statistics Poland (GUS)", "https://stat.gov.pl/en/topics/population/internationa-migration/main-directions-of-emigration-and-immigration-in-years-1966-2008,2,1.html"),
    ("Displaced persons and Polish repatriation", W + "Displaced_persons"),
    ("Displaced persons and Polish repatriation", W + "Repatriation_of_Poles"),
    ("Flight and expulsion of Germans", W + "Flight_and_expulsion_of_Germans_(1944%E2%80%931950)"),
    ("Greek Civil War refugees", W + "Greeks_in_Poland"),
    ("Kresy-Siberia", "https://kresy-siberia.org/"),
    ("Te Ara", "https://teara.govt.nz/en/poles"),
    ("Population transfers in the Soviet Union", W + "Population_transfer_in_the_Soviet_Union"),
    ("Population transfers in the Soviet Union", W + "Polish_population_transfers_(1944%E2%80%931946)"),
    ("Polish-Soviet population exchange", W + "Polish_population_transfers_(1944%E2%80%931946)"),
    ("Repatriation of Poles from the USSR", W + "Repatriation_of_Poles"),
    ("DHS Yearbook", "https://ohss.dhs.gov/topics/immigration/yearbook"),
    ("Statistical Yearbooks", "https://www.dhs.gov/yearbook-immigration-statistics"),
    ("Immigration and Naturalization Service, Annual Report", "https://archive.org/search?query=%22Annual+report+of+the+Immigration+and+Naturalization+Service%22"),
    ("Canada Year Book", "https://www66.statcan.gc.ca/acyb_000-eng.htm"),
    ("Manpower and Immigration", "https://publications.gc.ca/site/eng/search/search.html?q=immigration+statistics"),
    ("Employment and Immigration Canada", "https://publications.gc.ca/site/eng/search/search.html?q=immigration+statistics"),
    ("Facts and Figures", "https://publications.gc.ca/site/eng/search/search.html?q=facts+and+figures+immigration+overview"),
    ("IRCC open data", "https://open.canada.ca/data/en/dataset/f7e5498e-0ad8-4417-85c9-9b8aff9b9eda"),
]


def source_links(src):
    """Links for a source string: URLs written in it plus every matching LINK_RULES page; every source must get one."""
    urls = [u.rstrip(".,;)") for u in re.findall(r"https?://[^\s)]+", src)]
    urls += [u for k, u in LINK_RULES if k in src and u not in urls]
    assert urls, f"no link for source: {src}"
    return urls


def load_stock(cache, n3):
    """Return {(origin iso, destination iso, year): people} for pairs involving Poland."""
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / "un_ims_2024.xlsx"
    if not f.exists():
        req = urllib.request.Request(UN_URL, headers={"User-Agent": "Mozilla/5.0 poland-migration-map"})
        f.write_bytes(urllib.request.urlopen(req, timeout=180).read())
    ws = openpyxl.load_workbook(f, read_only=True)["Table 1"]
    stock, unmapped = {}, {}
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i == 10:
            assert list(r[7:15]) == STOCK_YEARS, f"unexpected year columns {r[7:15]}"
        if i <= 10 or r[4] is None or r[6] is None:
            continue
        dest, org = int(r[4]), int(r[6])
        if (dest == 616) == (org == 616) or max(dest, org) >= 900:
            continue  # not a Poland pair, or a regional aggregate
        other = org if dest == 616 else dest
        iso = n3.get(other)
        if iso is None:
            unmapped[other] = r[5] if dest == 616 else r[1]
            continue
        pair = (iso, "POL") if dest == 616 else ("POL", iso)
        for y, v in zip(STOCK_YEARS, r[7:15]):
            stock[pair + (y,)] = float(v or 0)
    return stock, unmapped


UN_SRC = "UN DESA, International Migrant Stock 2024, Table 1 (stock by destination and origin, both sexes), CC BY 3.0 IGO"
ABS_SRC = "ABS, Overseas Migration 2022-23 (tables 2.1, 3.1, 1.1), financial years to 2022-23"
ABS_METHOD = ("Overseas migrant arrivals of Poland-born people to Australia, summed over the financial years of the period. "
              "Arrivals are people who stay 12 of the next 16 months, so they include temporary migrants and returning residents, and did not necessarily come from Poland.")
PERMIT_SRC = "Eurostat, first residence permits by citizenship (migr_resfirst, Poland), reuse with attribution"
TP_SRC = "Eurostat, beneficiaries of temporary protection at the end of the month (migr_asytpsm, Poland)"


def un_basis(direction, start):
    if direction == "in":
        return (UN_SRC,
                "Growth between UN reference years in the number of people born in the country who live in Poland (shrinking stocks count as 0). It is net stock growth, not a count of moves.",
                "low",
                "Net stock growth understates arrivals: deaths and returns shrink the stock, and the foreign-born stock in Poland fell for most of the period, so inflows often show as zero.")
    low = start < 2005
    return (UN_SRC,
            "Growth between UN reference years in the number of Poland-born people living in the country (shrinking stocks count as 0). It is net stock growth, not a count of moves.",
            "low" if low else "medium",
            "The UN stocks for 1990-2000 are partly modelled, and net stock growth hides gross flows (deaths, returns and naturalisation shrink the stock)." if low else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", default=str(ROOT / "data" / "flows.json"))
    a = ap.parse_args()

    countries = json.loads((ROOT / "data" / "map.json").read_text("utf-8"))["countries"]
    names = {c["id"]: c["name"] for c in countries}
    n3 = {c["n3"]: c["id"] for c in countries if c["n3"]}
    names.update(PSEUDO)
    starts = list(range(FIRST, 2020 + 1, STEP))
    periods = [{"start": s, "end": s + STEP, "method": "curated" if s < 1990 else "stock"} for s in starts]
    periods[-1]["end"] = 2024  # the last UN DESA reference year is 2024, not 2025
    cells = {}  # (period index, iso) -> dict

    def cell(pi, iso):
        return cells.setdefault((pi, iso), {"in": 0, "out": 0, "conf": None, "notes": [], "b": {}})

    bases, base_idx = [], {}

    def reg(src, method, conf, why=None):
        assert conf != "low" or why, f"low confidence needs a reason: {src} / {method}"
        key = (src, method, conf, why)
        if key not in base_idx:
            base_idx[key] = len(bases)
            bases.append({"s": src, "m": method, "c": conf, "u": source_links(src), **({"w": why} if why else {})})
        return base_idx[key]

    # curated rows
    hist = json.loads((ROOT / "data" / "historical_1945_1989.json").read_text("utf-8"))["rows"]
    rank = {"low": 0, "medium": 1, "high": 2}
    replacements = []
    for r in hist:
        if r.get("replace"):
            replacements.append(r)  # applied after the stock stage, in place of the stock value
            continue
        assert r["period"] in starts and (r["period"] < 1990 or r.get("replace")), f"bad period {r}"
        assert r["country"] in names, f"unknown country {r['country']}"
        assert r["dir"] in ("in", "out") and r["people"] > 0
        c = cell(starts.index(r["period"]), r["country"])
        c[r["dir"]] += r["people"]
        c["b"][r["dir"]] = reg(r["source"], r["method"], r["confidence"], r.get("why"))
        c["notes"].append(f"{'To' if r['dir'] == 'in' else 'From'} Poland: {r['note']} Source: {r['source']}.")
        if c["conf"] is None or rank[r["confidence"]] < rank[c["conf"]]:
            c["conf"] = r["confidence"]

    # stock-change periods
    stock, unmapped = load_stock(pathlib.Path(a.cache), n3)
    dropped = {}
    for pi, p in enumerate(periods):
        if p["method"] != "stock":
            continue
        y0, y1 = p["start"], p["end"]
        for direction in ("in", "out"):
            vals = {}
            for (pob, por, y), s1 in stock.items():
                if y != y1:
                    continue
                # in: people born in the partner and living in Poland; out: Poland-born living in the partner
                if direction == "in" and (por != "POL" or pob == "POL"):
                    continue
                if direction == "out" and (pob != "POL" or por == "POL"):
                    continue
                partner = pob if direction == "in" else por
                d = s1 - stock.get((pob, por, y0), 0.0)
                if d >= MIN_PEOPLE:
                    vals[partner] = d
            for iso, d in sorted(vals.items(), key=lambda kv: -kv[1])[:KEEP_PER_DIRECTION]:
                if iso not in names:
                    dropped[iso] = dropped.get(iso, 0) + d
                    continue
                cell(pi, iso)[direction] += round(d)
                cell(pi, iso)["b"].setdefault(direction, reg(*un_basis(direction, p["start"])))

    for r in replacements:
        c = cell(starts.index(r["period"]), r["country"])
        c[r["dir"]] = r["people"]
        c["b"][r["dir"]] = reg(r["source"], r["method"], r["confidence"], r.get("why"))
        c["notes"].append(f"{'To' if r['dir'] == 'in' else 'From'} Poland: {r['note']} Source: {r['source']}.")
        c["conf"] = r["confidence"]

    # Every other destination with a UN Poland-born stock: no official arrivals series is used (except the
    # Eurostat override below), so the Australian method is applied: net inflow = change in stock + deaths.
    # "Settled" diasporas (large 1990 stock, or CAN/NZL) use the death rates calibrated on the ABS data;
    # the rest, mostly recent arrivals, split the stock into an old cohort dying at 4.5% and young arrivals at 0.4%.
    COHORT_RATE = {1990: .014, 1995: .0165, 2000: .019, 2005: .0215, 2010: .024, 2015: .0265, 2020: .029}
    OLD_RATE, YOUNG_RATE = 0.045, 0.004
    SETTLED_MIN_1990 = 20000

    def is_settled(iso):
        if iso in ("GBR", "IRL"):
            return False
        return iso in ("CAN", "NZL") or stock.get(("POL", iso, 1990), 0.0) >= SETTLED_MIN_1990

    def modelled_out(iso, p):
        y0, y1 = p["start"], p["end"]
        s0, s1 = stock.get(("POL", iso, y0)), stock.get(("POL", iso, y1))
        if s0 is None or s1 is None:
            return None
        yrs = y1 - y0
        if not is_settled(iso):
            base = stock.get(("POL", iso, 1990), 0.0)
            deaths = 0.0
            for k in range(yrs):
                cur = s0 + (s1 - s0) * (k + 0.5) / yrs
                old = min(cur, base * (1 - OLD_RATE) ** (y0 + k + 0.5 - 1990))
                deaths += old * OLD_RATE + (cur - old) * YOUNG_RATE
        else:
            deaths = COHORT_RATE[y0] * (s0 + s1) / 2 * yrs
        return max(0, round((s1 - s0 + deaths) / 100.0) * 100), s1 - s0, round(deaths)

    MOD_SRC = UN_SRC
    MOD_WHY_SETTLED = ("Modelled, not counted: no official arrivals series was used. The death rates are borrowed from Australia, whose Poland-born population may differ in age; "
                       "emigration and return are not subtracted, and the UN stock for 1990-2000 is partly modelled.")
    MOD_WHY_YOUNG = ("Modelled, not counted: no official arrivals series was used. The old-cohort death rate is an assumption, the UN stock for 1990-2000 is partly modelled, "
                     "and emigration and return are not subtracted.")
    modelled_isos = sorted({k[1] for k in stock if k[0] == "POL" and k[2] == 1990} | {k[1] for k in stock if k[0] == "POL"})
    for iso in modelled_isos:
        if iso in ("USA", "AUS", "POL") or iso not in names:
            continue
        for pi, p in enumerate(periods):
            if p["method"] != "stock":
                continue
            c = cells.get((pi, iso))
            if c and c["b"].get("out") is not None and c["out"] and any(
                    r["country"] == iso and r["dir"] == "out" and r["period"] == p["start"] for r in replacements):
                continue  # an explicit replacement row (official data) already covers this cell
            res = modelled_out(iso, p)
            if not res or res[0] < MIN_PEOPLE:
                continue
            val, ds, dth = res
            c = cell(pi, iso)
            c["out"] = val
            settled = is_settled(iso)
            c["b"]["out"] = reg(MOD_SRC,
                "Modelled net inflow of Poland-born people: change in the UN stock of Poland-born residents between reference years plus assumed deaths, " + (
                    "at the death rates calibrated on the ABS data for Australia (1.4% a year rising to 2.9%)." if settled
                    else "split between an old WWII-era cohort (4.5% a year) and young post-2004 arrivals (0.4% a year)."),
                "low", MOD_WHY_SETTLED if settled else MOD_WHY_YOUNG)
            how = (f"the Australian calibration ({COHORT_RATE[p['start']] * 100:.1f}% a year)" if settled
                   else "an old cohort dying at 4.5% a year plus young arrivals at 0.4%")
            c["notes"].append(f"From Poland: modelled net inflow {val:,} = change in stock {ds:+,} + assumed deaths {dth:,} ({how}). Source: {MOD_SRC}.")
            c["conf"] = "low"

    # Europe: official immigration with Poland as the country of previous residence (Eurostat) replaces the model
    # for every period whose calendar years are all present (up to two consecutive interior gaps are interpolated).
    yearly0 = json.loads((ROOT / "data" / "yearly.json").read_text("utf-8"))
    a2_0 = {c_["a2"]: c_["id"] for c_ in countries if c_.get("a2")}
    a2_0.update({"UK": "GBR", "EL": "GRC"})
    EU_SRC = "Eurostat, immigration by country of previous residence = Poland (migr_imm5prv, national statistics offices)"
    EU_METHOD = ("People registered or estimated as immigrating from Poland (previous residence Poland), summed over the calendar years of the period. "
                 "Definitions differ between countries (registrations or surveys, minimum length of stay), and the count is gross, so it exceeds net stock growth.")
    eu_unmapped = []
    # UK years Eurostat lacks (2007, 2019) come from the ONS International Passenger Survey, the survey behind the UK values.
    ips = json.loads((ROOT / "data" / "uk_ips_poland.json").read_text("utf-8"))["inflow"]
    for code, series in yearly0["from_pl"].items():
        iso = a2_0.get(code)
        if iso is None or iso not in names:
            eu_unmapped.append(code)
            continue
        ips_years = []
        if iso == "GBR":
            ips_years = sorted(y for y in ips if y not in series)
            series = {**{y: ips[y] for y in ips_years}, **series}
        for pi, p in enumerate(periods):
            last = 2024 if pi == len(periods) - 1 else p["end"] - 1
            ys = list(range(p["start"], last + 1))
            have = {y: series[str(y)] for y in ys if str(y) in series}
            if len(have) < 2:
                continue
            filled, interp, scaled = {}, [], None
            for y in ys:
                if y in have:
                    filled[y] = have[y]
                    continue
                lo = max((k for k in series if int(k) < y), default=None, key=int)
                hi = min((k for k in series if int(k) > y), default=None, key=int)
                if lo is None or hi is None or int(hi) - int(lo) > 3:
                    filled = None
                    break
                filled[y] = series[lo] + (series[hi] - series[lo]) * (y - int(lo)) / (int(hi) - int(lo))
                interp.append(y)
            if not filled and len(have) == len(ys) - 1 and len(ys) >= 5 and (ys[0] not in have or ys[-1] not in have):
                filled, interp, scaled = dict(have), [], ys[0] if ys[0] not in have else ys[-1]  # one end year missing
            if not filled or sum(filled.values()) < MIN_PEOPLE:
                continue
            total = round(sum(filled.values()) * (len(ys) / len(filled) if scaled else 1))
            c = cell(pi, iso)
            c["out"] = total
            extra = (" Missing years inside the period are interpolated." if interp else "") + (
                " If one end year of a period is missing, the other four years are scaled up by 5/4." if scaled else "")
            ips_used = [y for y in ys if str(y) in ips_years]
            src = EU_SRC + ("; years missing there taken from ONS International Passenger Survey table 4.03" if ips_used else "")
            extra += (f" Survey year{'s' if len(ips_used) > 1 else ''} {', '.join(map(str, ips_used))} come from the ONS International Passenger Survey, "
                      "a sample survey with a 95% interval of about plus or minus 25%.") if ips_used else ""
            c["b"]["out"] = reg(src, EU_METHOD + extra, "medium")
            c["notes"].append(f"From Poland: official immigration from Poland, {ys[0]}-{ys[-1]}: {total:,}."
                              + (f" {', '.join(map(str, ips_used))} taken from the ONS International Passenger Survey (table 4.03)." if ips_used else "")
                              + (f" Interpolated years: {', '.join(map(str, interp))}." if interp else "")
                              + (f" {scaled} is missing, so the other four years were scaled up by 5/4." if scaled else "") + f" Source: {EU_SRC}.")
            c["conf"] = "medium"

    # Iceland, Norway, Sweden, Denmark and Finland: the national statistics offices' yearly counts of moves to and from Poland replace
    # the model and Eurostat (their series are complete and, for Norway, revised since Eurostat's).
    NATIONAL = {
        "ISL": ("iceland_poland.json", "Statistics Iceland, External migration by sex, countries and citizenship 1986-2025 (table MAN01404), Poland as country of origin or destination",
                "Gross counts: immigrants include Icelanders returning from Poland, and emigrants include Poles going home."),
        "NOR": ("norway_poland.json", "Statistics Norway, Immigration, emigration and net immigration, by country of emigration/immigration 1967-2025 (table 07822), Poland as country of emigration or immigration",
                "Gross counts: immigrants include Norwegians returning from Poland, and emigrants include Poles going home."),
        "SWE": ("sweden_poland.json", "Statistics Sweden, Immigrations and emigrations by country of emi-/immigration (table ImmiEmiFlyttN, 2000-2024), Poland as country of emigration or immigration",
                "Gross counts: immigrants include Swedes returning from Poland, and emigrants include Poles going home."),
        "DNK": ("denmark_poland.json", "Statistics Denmark, StatBank tables INDVAN (Immigrations) and UDVAN (Emigrations), 1980-2025, Poland as country of last residence or destination",
                "Gross counts: immigrants include Danes returning from Poland, and emigrants include Poles going home."),
        "FIN": ("finland_poland.json", "Statistics Finland, Immigration and emigration by country of departure or arrival, sex and language (table 159p, 1990-2025), Poland as country of departure or arrival",
                "Gross counts: immigrants include Finns returning from Poland, and emigrants include Poles going home."),
        # a source given per direction as [(last year it covers, text)], when two tables are spliced
        "NLD": ("netherlands_poland.json", {
            "immigration": [(2025, "Statistics Netherlands (CBS), StatLine table 85671NED, Migration by country of departure or destination and country of birth (2014-2025), Poland as country of departure")],
            "emigration": [(2011, "Statistics Netherlands (CBS), StatLine table 82350NED, Emigrants by origin, country of destination and socio-economic category (2000-2011, discontinued; published in thousands to one decimal, so rounded to 100), Poland as country of destination"),
                           (2025, "Statistics Netherlands (CBS), StatLine table 85671NED, Migration by country of departure or destination and country of birth (2014-2025), emigration excluding administrative corrections, Poland as country of destination")]},
                "Gross counts: immigrants include Dutch people returning from Poland, and emigrants include Poles going home."),
        "BEL": ("belgium_poland.json", "Eurostat, emigration by country of next usual residence (migr_emi3nxt, 2010-2024), Belgium to Poland, from Belgium's National Register (Statbel)",
                "Gross counts: emigrants include Belgians moving to Poland, and Poles going home."),
        "AUT": ("austria_poland.json", "Statistik Austria, Wanderungen mit dem Ausland (Außenwanderungen) 2002-2025 nach Herkunfts- bzw. Zielland (Tabellensammlung, sheet T5, https://www.statistik.at/statistiken/bevoelkerung-und-soziales/bevoelkerung/migration-und-einbuergerung/wanderungen-mit-dem-ausland), Poland as country of origin or destination",
                "Gross counts: immigrants include Austrians returning from Poland, and emigrants include Poles going home; moves with unknown origin or destination (5-33% of Wegzuege, 33% in 2002, 12% in 2010, 5% in 2024) are not counted under Poland, so both are lower bounds."),
        "DEU": ("germany_poland.json", "Statistisches Bundesamt (Destatis), Wanderungsstatistik: Zuzuege and Fortzuege between Germany and Poland 1974-2024, as tabulated by the Federal Institute for Population Research (BiB) (https://www.bib.bund.de/DE/Fakten/Fakt/M13-Zuzuege-Fortzuege-Deutschland-Polen-ab-1974.html)",
                "Gross counts of all registered moves with no minimum stay: arrivals include ethnic German resettlers and Poles passing through, departures include Germans moving to Poland and Poles going home, and departures are under-recorded. 1990 is West Germany only. Eurostat's German series is about half of this from 2014 (probably its 12-month rule), and results from 2016 are only partly comparable with earlier years."),
        "ITA": ("italy_poland.json", "ISTAT, Migration (transfer of residence): immigrants by country of origin (28_185_DF_DCIS_MIGRAZIONI_3) and emigrants by country of next residence (28_185_DF_DCIS_MIGRAZIONI_6), 2002-2024, Poland, https://esploradati.istat.it/SDMXWS/rest/data/28_185_DF_DCIS_MIGRAZIONI_3/",
                "Gross counts of registrations from abroad and cancellations to abroad in the municipal registers, all citizenships: immigrants include Italians returning from Poland, emigrants include Poles going home. Registrations are not only new arrivals: 2003 (10,973) and 2007 (19,246) are far above the neighbouring years, probably because Poles already living in Italy registered (the 2002 regularisation, the EU-citizen registration rules), which I did not verify; people who leave without cancelling their registration are missed."),
        "ESP": ("spain_poland.json", "Eurostat, emigration by country of next usual residence (migr_emi3nxt, 2002-2024), Spain to Poland, from Spain's INE municipal registers",
                "Gross counts: emigrants include Spaniards moving to Poland, and Poles going home; people who leave without deregistering are missed."),
    }
    national_in = set()  # (iso, period index) whose to-Poland side comes from a national file
    for iso, (fname, src0, who) in NATIONAL.items():
        data = json.loads((ROOT / "data" / fname).read_text("utf-8"))
        method = ("People registered as moving between the country and Poland, all citizenships, summed over the calendar years of the period. " + who)
        for pi, p in enumerate(periods):
            if p["method"] != "stock" or iso not in names:
                continue
            ys = [str(y) for y in range(p["start"], (2024 if pi == len(periods) - 1 else p["end"] - 1) + 1)]
            for key, d_ in (("immigration", "out"), ("emigration", "in")):
                if any(y not in data[key] for y in ys):
                    continue  # the series starts later than this period, or the file lacks this direction
                tot = sum(data[key][y] for y in ys)
                if tot < NATIONAL_MIN:
                    continue
                src_ = src0 if isinstance(src0, str) else next(t for last, t in src0[key] if int(ys[-1]) <= last)
                c = cell(pi, iso)
                if d_ == "in":
                    national_in.add((iso, pi))
                c[d_] = tot
                c["b"][d_] = reg(src_, method, "medium")
                fill = [y for y in ys if y in data.get("interpolated", {}).get(key, [])]
                c["notes"].append(f"{'From' if d_ == 'out' else 'To'} Poland: {tot:,} registered moves {'to' if d_ == 'out' else 'from'} {names[iso]} {'from Poland' if d_ == 'out' else 'to Poland'}, {ys[0]}-{ys[-1]}."
                               + (f" {', '.join(fill)} is not published and is the average of the years either side." if fill else "") + f" Source: {src_}.")
                c["conf"] = "medium"

    # Other countries: Eurostat's emigration by country of next residence (migr_emi3nxt) gives the to-Poland side.
    # One missing interior year is interpolated (longer gaps can span series breaks); the national files above take precedence.
    eu_to = json.loads((ROOT / "data" / "eurostat_to_poland.json").read_text("utf-8"))["emigration"]
    TO_SRC = "Eurostat, emigration by country of next usual residence = Poland (migr_emi3nxt, national statistics offices)"
    TO_METHOD = ("People registered or estimated as emigrating to Poland (next residence Poland), all citizenships, summed over the calendar years of the period. "
                 "Definitions differ between countries (registrations or surveys, minimum length of stay), and the count is gross: it includes natives moving to Poland and Poles going home.")
    for code, series in eu_to.items():
        iso = a2_0.get(code)
        if iso is None or iso not in names:
            continue
        for pi, p in enumerate(periods):
            if p["method"] != "stock" or (iso, pi) in national_in or (iso in NATIONAL and iso != "AUT") or any(r["country"] == iso and r["dir"] == "in" and r["period"] == p["start"] for r in replacements):
                continue
            ys = list(range(p["start"], (2024 if pi == len(periods) - 1 else p["end"] - 1) + 1))
            filled, interp = {}, []
            for y in ys:
                if str(y) in series:
                    filled[y] = series[str(y)]
                    continue
                lo = max((int(k) for k in series if int(k) < y), default=None)
                hi = min((int(k) for k in series if int(k) > y), default=None)
                if lo is None or hi is None or hi - lo > 2:
                    filled = None
                    break
                filled[y] = series[str(lo)] + (series[str(hi)] - series[str(lo)]) * (y - lo) / (hi - lo)
                interp.append(y)
            if not filled:
                continue
            total = round(sum(filled.values()))
            if total < NATIONAL_MIN:
                continue
            survey = " UK values are estimates from the International Passenger Survey, a sample survey with a wide margin of error." if iso == "GBR" else ""
            c = cell(pi, iso)
            c["in"] = total
            c["b"]["in"] = reg(TO_SRC, TO_METHOD + survey, "medium")
            c["notes"].append(f"To Poland: {total:,} registered moves to Poland from {names[iso]}, {ys[0]}-{ys[-1]}."
                              + (f" {', '.join(map(str, interp))} is not published and is interpolated between the neighbouring years." if interp else "") + survey + f" Source: {TO_SRC}.")
            c["conf"] = "medium"

    # Australia: ABS overseas migrant arrivals of Poland-born people replace the modelled value from 2005
    abs_au = json.loads((ROOT / "data" / "australia_abs.json").read_text("utf-8"))
    for pi, p in enumerate(periods):
        fys = [f"{y}-{str(y + 1)[2:]}" for y in range(p["start"], p["start"] + 5)]
        have = [fy for fy in fys if fy in abs_au["arrivals"]]
        if p["start"] < 2005 or not have:
            continue
        arr = sum(abs_au["arrivals"][fy] for fy in have)
        dep = sum(abs_au["departures"][fy] for fy in have)
        nom = sum(abs_au["nom"][fy] for fy in have)
        c = cell(pi, "AUS")
        c["out"] = arr
        c["b"]["out"] = reg(ABS_SRC, ABS_METHOD, "medium")
        part = "" if len(have) == 5 else f" Only {len(have)} financial years ({have[0]} to {have[-1]}) are available for this period."
        c["notes"].append(
            f"From Poland: ABS overseas migrant arrivals of Poland-born people, {have[0]} to {have[-1]}: {arr:,} arrived, {dep:,} left, net {nom:+,}. "
            f"Arrivals are people who stay 12 of the next 16 months, include temporary migrants and returning residents, and did not necessarily come from Poland.{part} "
            f"Source: ABS Overseas Migration 2022-23, tables 2.1, 3.1 and 1.1.")
        c["conf"] = "medium"

    # first residence permits (Eurostat) per period, summed over calendar years start..end-1
    # (the last period is 2020-2024 inclusive). Eurostat uses UK and EL for GB and GR.
    yearly = json.loads((ROOT / "data" / "yearly.json").read_text("utf-8"))
    a2 = {c["a2"]: c["id"] for c in countries if c.get("a2")}
    a2.update({"UK": "GBR", "EL": "GRC"})
    pm_unmapped = {}
    PM_BASE = {
        "pm": reg(PERMIT_SRC, "First residence permits issued to non-EU citizens, all validities, summed over the calendar years of the period (2020-2024 covers five years).", "low",
                  "Permits are not arrivals: one person can receive several, permits valid under a year dominate, and refugees and EU citizens are largely missing."),
        "pm12": reg(PERMIT_SRC, "First residence permits issued to non-EU citizens that are valid 12 months or longer, summed over the calendar years of the period (2020-2024 covers five years).", "medium"),
    }
    tp_base = reg(TP_SRC, "People registered under temporary protection in Poland at the end of December of the period's last year (a stock, not arrivals).", "medium")
    for pi, p in enumerate(periods):
        last = 2024 if pi == len(periods) - 1 else p["end"] - 1
        yrs = [str(y) for y in range(p["start"], last + 1)]
        if not all(y in yearly["permits"] for y in yrs):
            continue
        p["permits"] = True
        for key, dur in (("pm", "TOTAL"), ("pm12", "M_GE12")):
            for y in yrs:
                for code, v in yearly["permits"][y][dur]["by"].items():
                    iso = a2.get(code)
                    if iso is None:
                        pm_unmapped[code] = pm_unmapped.get(code, 0) + v
                        continue
                    c = cell(pi, iso)
                    c[key] = c.get(key, 0) + v
                    c["b"][key] = PM_BASE[key]

    # temporary protection at the end of the period's last calendar year (2024 for the last period)
    tp_unmapped = {}
    for pi, p in enumerate(periods):
        last = 2024 if pi == len(periods) - 1 else p["end"] - 1
        entry = yearly.get("tp", {}).get(str(last))
        if not entry:
            continue
        p["tp"] = last
        for code, v in entry["by"].items():
            iso = a2.get(code)
            if iso is None:
                tp_unmapped[code] = tp_unmapped.get(code, 0) + v
                continue
            cell(pi, iso)["tp"] = v
            cell(pi, iso)["b"]["tp"] = tp_base

    flows = []
    for (pi, iso), c in sorted(cells.items()):
        if not (c["in"] or c["out"] or c.get("pm") or c.get("pm12") or c.get("tp")):
            continue
        row = {"p": pi, "c": iso, "in": c["in"], "out": c["out"]}
        for k in ("pm", "pm12", "tp"):
            if c.get(k):
                row[k] = c[k]
        row["b"] = {k: i for k, i in c["b"].items() if (c["in"] if k == "in" else c["out"] if k == "out" else c.get(k))}
        if c["conf"]:
            row["conf"] = c["conf"]
        if c["notes"]:
            row["notes"] = c["notes"]
        flows.append(row)

    used = sorted({f["c"] for f in flows})
    out = {
        "periods": periods,
        "countries": {i: names[i] for i in used},
        "flows": flows,
        "bases": bases,
    }
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"wrote {a.out}: {len(flows)} rows, {len(used)} countries")
    for pi, p in enumerate(periods):
        rows = [f for f in flows if f["p"] == pi]
        tin, tout = sum(f["in"] for f in rows), sum(f["out"] for f in rows)
        top = sorted(rows, key=lambda f: -(f["in"] + f["out"]))[:3]
        print(f"  {p['start']}-{p['end']} {p['method']:7} in {tin:>9,} out {tout:>9,}  top: "
              + ", ".join(f"{t['c']}({t['in']:,}/{t['out']:,})" for t in top))
    if tp_unmapped:
        print("  protection citizenships with no map shape (ignored):", tp_unmapped)
    if pm_unmapped:
        print("  permit citizenships with no map shape (ignored):", {k: v for k, v in sorted(pm_unmapped.items(), key=lambda kv: -kv[1])[:8]})
    if unmapped:
        print("  UN countries with no map shape (ignored):", unmapped)
    if dropped:
        print("  dropped (no map shape):", {k: round(v) for k, v in sorted(dropped.items(), key=lambda kv: -kv[1])})


if __name__ == "__main__":
    main()
