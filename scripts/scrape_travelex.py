"""Scrape Travelex.si plane ski trips: pool+sauna in description, 6p Óriási pricing."""
import json
import re
import urllib.request
from bs4 import BeautifulSoup

RESORTS = {
    "Montgenèvre": "https://travelex.si/siutjaink/franciaorszag/montgenevre-80km/szallas",
    "Serre Chevalier": "https://travelex.si/siutjaink/franciaorszag/serre-chevalier-250km/szallas",
    "Les 2 Alpes": "https://travelex.si/siutjaink/franciaorszag/les-2-alpes-225km/szallas",
    "Alpe d'Huez (Auris)": "https://travelex.si/siutjaink/franciaorszag/alpe-d-huez-250km/szallas",
    "3 Vallées": "https://travelex.si/siutjaink/franciaorszag/3-volgy-600km/szallas",
    "Mont Blanc": "https://travelex.si/siutjaink/franciaorszag/mont-blanc/szallas",
}

# RT HUF — updated 2026-09-14 travelex.si/repulos-siutak
FLIGHTS_TORINO = {
    "2027.01.02": 44090 + 11490,
    "2027.01.16": 26790 + 30690,
    "2027.01.23": 88190 + 18369,  # Ryanair return cheapest
    "2027.01.30": 88190 + 26773,
    "2027.03.06": 47890 + 18369,
    "2027.03.13": 44090 + 18369,
}
FLIGHTS_MILANO = {
    "2027.01.16": 8790 + 7690,
    "2027.01.23": 47890 + 30690,
    "2027.01.30": 15290 + 26773,
    "2027.03.06": 8790 + 18369,
}

HUF_PER_EUR = 400


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8", errors="replace")


def has_pool_and_sauna(text: str) -> bool:
    low = text.lower()
    pool = any(w in low for w in ("medence", "jacuzzi", "masszázsmedence"))
    sauna = "szauna" in low
    return pool and sauna


def pick_6p_col_index(headers: list[str]) -> tuple[int | None, str | None]:
    best_i, best_label, best_score = None, None, -1
    for i, h in enumerate(headers):
        hl = h.lower()
        if "6" not in hl:
            continue
        if re.search(r"\b8\b", hl) and "6" in hl[:6]:
            continue
        score = 0
        if "óriási" in hl or "ó:" in hl:
            score += 12
        if "6 x 6" in hl.replace("×", " x "):
            score += 8
        if re.fullmatch(r"6\s*x\s*6\s*fős", hl.strip()):
            score += 7
        if "tágas" in hl or "t:" in hl:
            score += 4
        if score > best_score:
            best_score, best_i, best_label = score, i, h
    return best_i, best_label


def parse_prices(cell_text: str) -> tuple[int | None, int | None]:
    if "megtelt" in cell_text.lower():
        return None, None
    prices = [int(x) for x in re.findall(r"(\d+)\s*€", cell_text)]
    if not prices:
        return None, None
    pkg = prices[1] if len(prices) >= 2 else prices[0]
    empty = prices[3] if len(prices) >= 4 else None
    return pkg, empty


def week_in_plane_dates(week: str, plane_dates: str) -> bool:
    if not plane_dates:
        return False
    if week in plane_dates:
        return True
    # 2027.03.13 -> 03.13 or 03.13-tól
    parts = week.split(".")
    if len(parts) == 3:
        md = f"{parts[1]}.{parts[2]}"
        if md in plane_dates:
            return True
    return False


def flight_for_week(week: str, resort: str) -> int | None:
    if resort == "Mont Blanc":
        return FLIGHTS_MILANO.get(week) or FLIGHTS_TORINO.get(week)
    return FLIGHTS_TORINO.get(week) or FLIGHTS_MILANO.get(week)


def parse_resort(html: str, resort: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    for block in soup.select("div.col-12.mb-4"):
        h2 = block.find("h2")
        if not h2:
            continue
        name = h2.get_text(strip=True)
        if not re.search(r"Sz[aá]ll[aá]s\s+\d+", name, re.I):
            continue

        section_text = block.get_text(" ", strip=True)

        if not has_pool_and_sauna(section_text):
            continue

        plane_m = re.search(
            r"Repülővel foglalható:\s*(.+?)(?:\s*Extrák|\s*Apartmanok felszereltsége|\s*Távolság a sípályáktól)",
            section_text,
        )
        if not plane_m:
            plane_m = re.search(r"Repülővel foglalható:\s*(.+?)(?:\s{2,}|$)", section_text)
        if not plane_m:
            continue
        plane_dates = plane_m.group(1).strip()

        table = block.find("table")
        if not table:
            continue

        header_cells = table.find("tr")
        if not header_cells:
            continue
        headers = [th.get_text(" ", strip=True) for th in header_cells.find_all("th")]
        if not headers:
            headers = [td.get_text(" ", strip=True) for td in header_cells.find_all("td")]
        col_idx, col_label = pick_6p_col_index(headers[1:] if headers else [])
        if col_idx is None:
            continue
        # price columns offset by 1 (first col is dates)
        price_col = col_idx + 1

        prices = []
        for row in table.select("tr.timeslot-flight"):
            date_td = row.select_one("td.timeslot-dates")
            if not date_td:
                continue
            date_text = date_td.get_text(" ", strip=True)
            m = re.search(r"(2027\.\d{2}\.\d{2})", date_text)
            if not m:
                continue
            week = m.group(1)
            cells = row.find_all("td")
            if price_col >= len(cells):
                continue
            pkg, empty = parse_prices(cells[price_col].get_text(" ", strip=True))
            if pkg is None:
                continue
            if not week_in_plane_dates(week, plane_dates):
                continue
            prices.append(
                {
                    "week": week,
                    "pkg_pp": pkg,
                    "empty_bed_pp": empty,
                    "room_type": col_label,
                }
            )

        if prices:
            # Note if sauna/pool are paid extras
            extras = ""
            em = re.search(r"Extrák az árban:\s*([^\.]+)", section_text)
            if em:
                extras = em.group(1)[:200]
            paid_sauna = "feláras: szauna" in section_text.lower() or "fizetős: szauna" in section_text.lower()

            results.append(
                {
                    "resort": resort,
                    "name": name,
                    "plane_dates": plane_dates,
                    "extras_included": extras,
                    "sauna_paid_extra": paid_sauna,
                    "prices": prices,
                }
            )

    return results


def main():
    all_props = []
    for resort, url in RESORTS.items():
        try:
            props = parse_resort(fetch(url), resort)
            all_props.extend(props)
            print(f"{resort}: {len(props)} matching properties")
        except Exception as exc:
            print(f"{resort}: ERROR {exc}")

    candidates = []
    for prop in all_props:
        for p in prop["prices"]:
            flight = flight_for_week(p["week"], prop["resort"])
            if flight is None:
                continue
            all_in = round(p["pkg_pp"] + flight / HUF_PER_EUR)
            candidates.append(
                {
                    "resort": prop["resort"],
                    "name": prop["name"],
                    "week": p["week"],
                    "pkg_pp": p["pkg_pp"],
                    "empty_bed_pp": p["empty_bed_pp"],
                    "room_type": p["room_type"],
                    "flight_huf": flight,
                    "all_in_eur": all_in,
                    "sauna_paid_extra": prop["sauna_paid_extra"],
                    "extras_included": prop["extras_included"],
                    "plane_dates": prop["plane_dates"],
                }
            )

    candidates.sort(key=lambda x: (x["all_in_eur"], x["pkg_pp"]))

    print("\n=== TOP 25 cheapest (package + flight, 6p room, pool+szauna in description) ===")
    for c in candidates[:25]:
        flag = " [szauna feláras]" if c["sauna_paid_extra"] else ""
        print(
            f"{c['all_in_eur']:>4} EUR/pp | {c['resort']:<20} | {c['name'][:42]:<42} | "
            f"{c['week']} | pkg {c['pkg_pp']} + flt {c['flight_huf']}{flag}"
        )

    # Best per resort
    print("\n=== Cheapest week per resort ===")
    by_resort = {}
    for c in candidates:
        if c["resort"] not in by_resort or c["all_in_eur"] < by_resort[c["resort"]]["all_in_eur"]:
            by_resort[c["resort"]] = c
    for resort in RESORTS:
        if resort in by_resort:
            c = by_resort[resort]
            print(f"{c['all_in_eur']} EUR/pp — {resort} — {c['name']} — {c['week']}")

    out = r"C:\Users\ifjab\Projects\3-valleys-ski-trip\scrape_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"properties": all_props, "ranked": candidates}, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(candidates)} ranked options to scrape_results.json")


if __name__ == "__main__":
    main()
