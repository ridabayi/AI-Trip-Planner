import os
import json
import base64
import mimetypes
from datetime import date, time, timedelta
from io import StringIO
import textwrap
import requests
import pandas as pd
import urllib.parse

import streamlit as st
from dotenv import load_dotenv

# ---- Your planner ----
from src.Core.planner import TravelPlanner

# ---------------------- Config signature dev ----------------------
SIGNATURE_NAME = "RIDA BAYi"
# Mets ici le chemin local de ta photo (ex: "assets/rida.jpg") ou une URL
SIGNATURE_PHOTO = "assets/rida.jpg"

# ---------------------- Page / theme ----------------------
st.set_page_config(
    page_title="AI Travel Planner",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Compact UI CSS ----------
st.markdown("""
<style>
h1, h2, h3 { margin: 0.2rem 0 0.6rem 0; }
h4, h5, h6, p { margin: 0.1rem 0 0.35rem 0; }
.block-container { padding-top: 1.2rem; padding-bottom: 1.2rem; }
.card { border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 12px;
        background: rgba(255,255,255,0.02); }
.card h4 { margin-bottom: 0.35rem; }
.meta { font-size: 0.9rem; opacity: 0.8; }
.badge { padding: 2px 8px; border-radius: 999px; font-size: 0.75rem;
         border: 1px solid rgba(255,255,255,0.12); margin-right: 6px;}
img.thumb { width: 100%; height: 180px; object-fit: cover; border-radius: 10px; }
.smallgap > div { padding-right: 8px; }

/* Tables compactes */
[data-testid="stScrollableBlock"] table { font-size: 0.92rem; }
[data-testid="stDataFrame"] tbody tr { height: 36px; }

/* Badge signature fixe */
#signature-badge {
  position: fixed; right: 16px; bottom: 14px; z-index: 1000;
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; border-radius: 999px;
  backdrop-filter: blur(6px);
  background: rgba(0,0,0,0.35);
  border: 1px solid rgba(255,255,255,0.18);
}
#signature-badge img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
#signature-badge span { font-size: 0.85rem; opacity: .9; }
</style>
""", unsafe_allow_html=True)

# ---------------------- Helpers ----------------------
def ensure_itinerary_dict(itin):
    """Normalise la sortie du planner."""
    if isinstance(itin, dict):
        return itin
    today = date.today().isoformat()
    return {
        "city": "Unknown",
        "days": [
            {
                "date": today,
                "summary": "Generated itinerary",
                "stops": [
                    {
                        "time": "09:00",
                        "name": "Your plan",
                        "category": "general",
                        "lat": None,
                        "lon": None,
                        "duration_min": None,
                        "cost_est": None,
                        "notes": str(itin),
                    }
                ],
            }
        ],
    }

def itinerary_to_markdown_legacy(itin: dict) -> str:
    """Markdown si on a l'ancien format days/stops."""
    lines = [f"# ✈️ Itinerary: {itin.get('city','')}\n"]
    for d in itin.get("days", []):
        lines.append(f"## {d.get('date','')}")
        if d.get("summary"):
            lines.append(d["summary"])
        stops = d.get("stops", [])
        for s in stops:
            t = s.get("time", "--:--")
            nm = s.get("name", "Stop")
            cat = s.get("category") or ""
            dur = s.get("duration_min")
            cost = s.get("cost_est")
            notes = s.get("notes") or ""
            meta = []
            if cat: meta.append(cat)
            if dur: meta.append(f"{dur} min")
            if isinstance(cost, (int, float)): meta.append(f"€{cost:.2f}")
            meta_txt = f" _({' • '.join(meta)})_" if meta else ""
            lines.append(f"- **{t}** — **{nm}**{meta_txt}")
            if notes:
                lines.append(f"  - {notes}")
        lines.append("")
    return "\n".join(lines)

def itinerary_to_json(itin: dict) -> str:
    return json.dumps(itin, ensure_ascii=False, indent=2)

def itinerary_to_ics(itin: dict, default_start="09:00"):
    # Minimal iCalendar export
    def yyyymmdd(d): return d.replace("-", "")
    buf = StringIO()
    buf.write("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//AI Travel Planner//EN\n")
    for d in itin.get("days", []):
        day_str = d.get("date")
        if not day_str:
            continue
        for s in d.get("stops", []):
            name = s.get("name", "Visit")
            notes = s.get("notes", "")
            t = s.get("time") or default_start
            tclean = (t if ":" in t else default_start).replace(":", "") + "00"
            buf.write("BEGIN:VEVENT\n")
            buf.write(f"DTSTART:{yyyymmdd(day_str)}T{tclean}\n")
            buf.write(f"SUMMARY:{name}\n")
            if notes:
                note = " ".join(notes.split())
                note_wrapped = textwrap.fill(note, width=70)
                buf.write(f"DESCRIPTION:{note_wrapped}\n")
            buf.write("END:VEVENT\n")
    buf.write("END:VCALENDAR\n")
    return buf.getvalue()

def extract_points_for_map(itin: dict):
    pts = []
    for d in itin.get("days", []):
        for s in d.get("stops", []):
            lat, lon = s.get("lat"), s.get("lon")
            if lat is not None and lon is not None:
                pts.append({"lat": float(lat), "lon": float(lon), "name": s.get("name",""), "time": s.get("time","")})
    return pts

def has_agent_markdown(itin: dict) -> bool:
    return isinstance(itin, dict) and "markdown" in itin and isinstance(itin["markdown"], str) and itin["markdown"].strip() != ""

def get_agent_day_maps(itin: dict, day_idx: int):
    try:
        return itin["days"][day_idx].get("maps", {}) or {}
    except Exception:
        return {}

def get_agent_day_pois(itin: dict, day_idx: int):
    try:
        return itin["days"][day_idx].get("pois", []) or []
    except Exception:
        return []

# ---------- Image fetchers (Wikipedia + Wikidata) ----------
WIKI_LANGS_ORDER = ["fr", "en", "ar", "es"]

def _wiki_search_image_candidates(query: str, lang: str, limit: int = 5):
    """Retourne des candidats (thumbnail_url, title, pageid) depuis Wikipedia(lang)."""
    try:
        r = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": limit,
                "prop": "pageimages|pageterms|categories",
                "piprop": "thumbnail",
                "pithumbsize": 800,
            },
            timeout=6,
        )
        pages = (r.json().get("query") or {}).get("pages") or {}
        out = []
        for _, pg in pages.items():
            cats = [c.get("title","") for c in pg.get("categories", [])] if "categories" in pg else []
            if any("disambiguation" in c.lower() or "homonymie" in c.lower() for c in cats):
                continue
            thumb = (pg.get("thumbnail") or {}).get("source")
            if thumb:
                out.append((thumb, pg.get("title",""), pg.get("pageid")))
        return out
    except Exception:
        return []

def _wikidata_image_filename(label: str, city: str, lang: str):
    """Utilise Wikidata pour chercher P18 (fichier image Commons)."""
    try:
        term = f"{label} ({city})"
        r = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "format": "json",
                "language": lang,
                "type": "item",
                "search": term,
                "limit": 3,
            },
            timeout=6,
        )
        search = r.json().get("search") or []
        if not search:
            r = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": lang,
                    "type": "item",
                    "search": label,
                    "limit": 3,
                },
                timeout=6,
            )
            search = r.json().get("search") or []
        if not search:
            return None

        qid = search[0]["id"]
        r2 = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": qid,
                "props": "claims",
            },
            timeout=6,
        )
        claims = (r2.json().get("entities") or {}).get(qid, {}).get("claims") or {}
        p18 = claims.get("P18")
        if not p18:
            return None
        filename = p18[0]["mainsnak"]["datavalue"]["value"]
        return filename
    except Exception:
        return None

def _commons_thumb_from_filename(filename: str, width: int = 800):
    return f"https://commons.wikimedia.org/w/thumb.php?f={urllib.parse.quote(filename)}&w={width}"

@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_place_image(label: str, city: str) -> str | None:
    """Image simple (peut servir de fallback)."""
    # 1) Wikipedia multi-lang
    query_variants = [f"{label}, {city}", f"{label} {city}", label]
    for lang in WIKI_LANGS_ORDER:
        for q in query_variants:
            cands = _wiki_search_image_candidates(q, lang=lang, limit=5)
            if cands:
                return cands[0][0]
    # 2) Wikidata P18
    for lang in WIKI_LANGS_ORDER:
        fn = _wikidata_image_filename(label, city, lang)
        if fn:
            return _commons_thumb_from_filename(fn, width=800)
    return None

def get_unique_place_image(label: str, city: str, used_urls: set) -> str | None:
    """Assure une image non déjà utilisée (dé-duplication)."""
    query_variants = [f"{label}, {city}", f"{label} {city}", f"{label} in {city}", f"{label} (landmark)", label]
    for lang in WIKI_LANGS_ORDER:
        for q in query_variants:
            cands = _wiki_search_image_candidates(q, lang=lang, limit=8)
            for url, _, _ in cands:
                if url not in used_urls:
                    used_urls.add(url)
                    return url
    for lang in WIKI_LANGS_ORDER:
        fn = _wikidata_image_filename(label, city, lang)
        if fn:
            url = _commons_thumb_from_filename(fn, width=800)
            if url not in used_urls:
                used_urls.add(url)
                return url
    return None

# ---------- Helpers Table view ----------
def _maps_search_url(label: str, address: str = "") -> str:
    q = f"{label}, {address}".strip(", ")
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(q)}"

def _get_poi_link(day: dict, idx: int, name: str, addr: str) -> str:
    pois = day.get("pois") or []
    if idx < len(pois):
        link = pois[idx].get("map_link")
        if link:
            return link
    return _maps_search_url(name, addr)

def day_to_dataframe(day: dict, city: str) -> pd.DataFrame:
    """DataFrame lisible pour un 'day' (stops synthétisés si agent)."""
    rows = []
    stops = day.get("stops", [])
    used_urls = set()
    for i, s in enumerate(stops):
        name = s.get("name", "") or "POI"
        addr = s.get("notes", "") or ""
        img_url = get_unique_place_image(name, city, used_urls)
        rows.append({
            "Time": s.get("time", ""),
            "Place": name,
            "Category": s.get("category", ""),
            "Duration (min)": s.get("duration_min"),
            "Cost (€)": s.get("cost_est"),
            "Map": _get_poi_link(day, i, name, addr),
            "Image": img_url,
            "Notes": addr
        })
    return pd.DataFrame(rows)

# ---------------------- Load env ----------------------
load_dotenv()

# ---------------------- Header ----------------------
st.title("🧭 AI Travel Itinerary Planner")
st.caption("Plan smarter trips with AI. Enter your city, choose interests & preferences, then export to Markdown/JSON/ICS.")

# ---------------------- Sidebar controls ----------------------
with st.sidebar:
    st.header("⚙️ Trip Preferences")
    city = st.text_input("City", placeholder="e.g., Paris")
    interests_raw = st.text_input("Interests (comma-separated)", placeholder="museums, coffee, parks")
    trip_days = st.number_input("Number of days", min_value=1, max_value=14, value=1)
    start_date = st.date_input("Start date", value=date.today())
    pace = st.selectbox("Pace", ["Relaxed", "Balanced", "Packed"], index=1)
    budget = st.select_slider("Budget per day (approx)", options=[50, 100, 150, 200, 300, 500], value=150, help="In EUR per traveler")
    start_time = st.time_input("Default start time", value=time(9, 0))
    travelers = st.number_input("Travelers", min_value=1, max_value=10, value=2)
    include_food = st.toggle("Include food stops", value=True)
    include_kids = st.toggle("Family-friendly focus", value=False)
    include_outdoors = st.toggle("Prefer outdoor activities", value=False)
    transport_mode = st.selectbox("Transport mode (for Google Maps)", ["walking", "bicycling", "driving", "transit"], index=0)

    st.divider()
    st.subheader("Actions")
    gen_btn = st.button("✨ Generate Itinerary", type="primary")
    reset_btn = st.button("↺ Reset")

if reset_btn:
    st.session_state.clear()
    st.rerun()

if "itinerary" not in st.session_state:
    st.session_state["itinerary"] = None

# ---------------------- Generation ----------------------
if gen_btn:
    if not city or not interests_raw:
        st.warning("Please provide both a city and at least one interest.")
    else:
        interests = [i.strip() for i in interests_raw.split(",") if i.strip()]
        with st.spinner("Planning your trip…"):
            planner = TravelPlanner()
            planner.set_city(city)
            planner.set_interests(", ".join(interests))

            try: planner.set_days(int(trip_days))
            except Exception: pass
            try: planner.set_start_date(start_date.isoformat())
            except Exception: pass
            try: planner.set_preferences({
                "pace": pace.lower(),
                "budget_per_day_eur": int(budget),
                "default_start_time": start_time.strftime("%H:%M"),
                "travelers": int(travelers),
                "include_food": bool(include_food),
                "family_friendly": bool(include_kids),
                "prefer_outdoors": bool(include_outdoors),
            })
            except Exception: pass
            try: planner.set_transport_mode(transport_mode)
            except Exception: pass

            try:
                raw_itinerary = planner.create_itinerary()
            except AttributeError:
                raw_itinerary = planner.create_itineary()
            except Exception as e:
                st.error(f"Planner error: {e}")
                raw_itinerary = "Unable to generate itinerary. Please adjust inputs and try again."

            itinerary = ensure_itinerary_dict(raw_itinerary)
            itinerary["city"] = city

            # ---------- Synthesize stops from POIs if needed ----------
            def _synthesize_stops_from_agent(itin: dict, default_start="09:00"):
                days = itin.get("days", [])
                if not days: return itin
                has_stops = any("stops" in d and d["stops"] for d in days)
                has_agent = any("sections" in d or "pois" in d for d in days) or ("markdown" in itin)
                if has_stops or not has_agent:
                    return itin
                for d in days:
                    pois = d.get("pois", [])
                    t_h, t_m = map(int, default_start.split(":")) if ":" in default_start else (9,0)
                    stops = []
                    for p in pois:
                        nm = p.get("label") or p.get("name") or "POI"
                        addr = p.get("address") or ""
                        cat = p.get("category") or "general"
                        cost = p.get("est_cost_eur")
                        time_txt = f"{t_h:02d}:{t_m:02d}"
                        stops.append({
                            "time": time_txt,
                            "name": nm,
                            "category": cat,
                            "lat": None, "lon": None,
                            "duration_min": 90 if cat != "food" else 60,
                            "cost_est": float(cost) if isinstance(cost, (int, float)) else None,
                            "notes": addr
                        })
                        t_m += 90
                        while t_m >= 60: t_m -= 60; t_h += 1
                    d["stops"] = stops
                return itin

            itinerary = _synthesize_stops_from_agent(itinerary, default_start=start_time.strftime("%H:%M"))
            st.session_state["itinerary"] = itinerary

# ---------------------- Main content ----------------------
if st.session_state["itinerary"] is None:
    st.info("Start by entering your destination & interests in the sidebar, then click **Generate Itinerary**.")
    st.stop()

itin = st.session_state["itinerary"]

# KPIs
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("City", itin.get("city", "—"))
with col2:
    st.metric("Days", len(itin.get("days", [])))
with col3:
    total_stops = sum(len(d.get("stops", [])) for d in itin.get("days", []))
    st.metric("Stops", total_stops if total_stops else "—")
with col4:
    est_cost = 0.0
    for d in itin.get("days", []):
        for s in d.get("stops", []):
            c = s.get("cost_est")
            if isinstance(c, (int, float)): est_cost += c
    st.metric("Est. Total Cost", f"€{est_cost:,.0f}" if est_cost else "—")

# Tabs
tab_overview, tab_table, tab_map, tab_day, tab_export = st.tabs(["Overview", "Table", "Map", "Day-by-day", "Export"])

with tab_overview:
    st.subheader("🗒️ Overview")

    if has_agent_markdown(itin):
        st.markdown(itin["markdown"])
        st.divider()

    st.subheader("📍 Points d’intérêt (tous les jours)")
    for day_idx, day in enumerate(itin.get("days", [])):
        st.markdown(f"### Jour {day_idx+1} — {day.get('date','')}")
        pois = get_agent_day_pois(itin, day_idx)
        if not pois:
            pois = [{"label": s.get("name",""), "address": s.get("notes","")} for s in day.get("stops", [])]
        if not pois:
            st.caption("Aucun POI pour ce jour.")
            continue

        used_urls = set()  # dé-dup images pour ce jour
        cols = st.columns(3, gap="small")
        for i, poi in enumerate(pois):
            with cols[i % 3]:
                label = poi.get("label") or poi.get("name") or "POI"
                addr = poi.get("address") or ""
                link = poi.get("map_link")
                img = get_unique_place_image(label, itin.get("city",""), used_urls)

                st.markdown('<div class="card">', unsafe_allow_html=True)
                if img:
                    st.image(img, use_container_width=True)
                st.markdown(f"**{label}**")
                if addr:
                    st.markdown(f'<span class="meta">{addr}</span>', unsafe_allow_html=True)

                row = st.columns([1,1,1])
                with row[0]:
                    if link:
                        st.link_button(f"Carte {day_idx+1}-{i+1}", link, use_container_width=True)
                with row[1]:
                    maps = get_agent_day_maps(itin, day_idx)
                    if maps.get("dir_link") and i % 3 == 0:
                        st.link_button(f"Route {day_idx+1}", maps["dir_link"], use_container_width=True)
                with row[2]:
                    est_cost = poi.get("est_cost_eur")
                    if not est_cost and i < len(day.get("stops", [])):
                        est_cost = day["stops"][i].get("cost_est")
                    st.button(
                        f"€{int(est_cost)}" if isinstance(est_cost,(int,float)) else "€—",
                        disabled=True,
                        use_container_width=True,
                        key=f"price_{day_idx}_{i}"
                    )
                st.markdown('</div>', unsafe_allow_html=True)

with tab_table:
    st.subheader("📊 Itinerary (table view)")
    for idx, day in enumerate(itin.get("days", [])):
        st.markdown(f"### Day {idx+1} — {day.get('date','')}")
        df = day_to_dataframe(day, itin.get("city",""))
        if df.empty:
            st.caption("No stops for this day.")
            continue
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Map": st.column_config.LinkColumn("Map"),
                "Image": st.column_config.ImageColumn("Image", width="medium"),
                "Duration (min)": st.column_config.NumberColumn("Duration (min)", format="%.0f"),
                "Cost (€)": st.column_config.NumberColumn("Cost (€)", format="%.2f"),
            }
        )
        st.divider()

with tab_map:
    st.subheader("🗺️ Map & Routes")

    has_any_route = False
    for idx, day in enumerate(itin.get("days", [])):
        maps = get_agent_day_maps(itin, idx)
        dir_link = maps.get("dir_link")
        if dir_link:
            has_any_route = True
            with st.container(border=True):
                st.markdown(f"### {day.get('date','')} — Global Route")
                st.link_button(f"Open in Google Maps — Day {idx+1}", dir_link, use_container_width=True)
                pois = get_agent_day_pois(itin, idx)
                if pois:
                    st.markdown("**POIs**")
                    for p in pois:
                        label = p.get("label") or p.get("name") or "POI"
                        addr = p.get("address") or ""
                        link = p.get("map_link")
                        line = f"- **{label}**" + (f" — {addr}" if addr else "")
                        if link: line += f" • [Carte]({link})"
                        st.markdown(line)

    if not has_any_route:
        st.caption("Pas de lien d’itinéraire global fourni par l’agent — utilisez la carte si des lat/lon sont renseignés ci-dessous.")

    points = extract_points_for_map(itin)
    if points:
        st.map(points, latitude="lat", longitude="lon")
        with st.expander("Points shown"):
            st.dataframe(points, use_container_width=True)

with tab_day:
    st.subheader("📆 Day-by-day plan")
    for i, day in enumerate(itin.get("days", [])):
        with st.container(border=True):
            st.markdown(f"### {day.get('date','')}")
            if "sections" in day:  # agent
                secs = day["sections"]
                for key in ["morning","lunch","afternoon","evening","logistics","rain_plan","recap"]:
                    xs = secs.get(key, [])
                    if xs:
                        st.markdown(f"**{key.capitalize()}**")
                        for b in xs:
                            st.write(f"- {b}")
            else:  # legacy stops
                stops = day.get("stops", [])
                if not stops:
                    st.caption("No stops for this day.")
                    continue
                for s in stops:
                    left, right = st.columns([2, 1])
                    with left:
                        st.markdown(f"**{s.get('time','--:--')}** — **{s.get('name','Stop')}**")
                        meta = []
                        if s.get("category"): meta.append(s["category"])
                        if s.get("duration_min"): meta.append(f"{s['duration_min']} min")
                        if isinstance(s.get("cost_est"), (int, float)): meta.append(f"€{s['cost_est']:.2f}")
                        if meta:
                            st.caption(" • ".join(meta))
                        if s.get("notes"):
                            st.write(s["notes"])
                    with right:
                        st.text_input("Time", value=s.get("time",""), key=f"time_{day['date']}_{s.get('name','')}")
                        st.text_input("Notes", value=s.get("notes",""), key=f"notes_{day['date']}_{s.get('name','')}")

with tab_export:
    st.subheader("📤 Export")
    md = itin["markdown"] if has_agent_markdown(itin) else itinerary_to_markdown_legacy(itin)
    js = itinerary_to_json(itin)
    ics = itinerary_to_ics(itin, default_start=start_time.strftime("%H:%M"))

    st.download_button("Download Markdown", md, file_name="itinerary.md")
    st.download_button("Download JSON", js, file_name="itinerary.json")
    st.download_button("Download Calendar (.ics)", ics, file_name="itinerary.ics")

    st.divider()
    st.text_area("Preview (Markdown)", md, height=300)

# ---------------------- Signature badge ----------------------
def _data_uri(path_or_url: str) -> str | None:
    if not path_or_url:
        return None
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if os.path.exists(path_or_url):
        mime = mimetypes.guess_type(path_or_url)[0] or "image/png"
        with open(path_or_url, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    return None

photo_src = _data_uri(SIGNATURE_PHOTO)
if photo_src:
    st.markdown(f'''
    <div id="signature-badge">
      <img src="{photo_src}" alt="author"/>
      <span>Créé par <strong>{SIGNATURE_NAME}</strong></span>
    </div>
    ''', unsafe_allow_html=True)
else:
    st.markdown(f'''
    <div id="signature-badge">
      <span>Créé par <strong>{SIGNATURE_NAME}</strong></span>
    </div>
    ''', unsafe_allow_html=True)
