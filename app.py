import json
from datetime import date, time, timedelta
from io import StringIO
import textwrap

import streamlit as st
from dotenv import load_dotenv

# ---- Your planner ----
from src.Core.planner import TravelPlanner

# ---------------------- Page / theme ----------------------
st.set_page_config(
    page_title="AI Travel Planner",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------- Helpers ----------------------
def ensure_itinerary_dict(itin):
    """
    Normalize whatever TravelPlanner returns into a standard dict:
    {
      "city": str,
      "days": [
        {
          "date": "YYYY-MM-DD",
          "summary": "text",
          "stops": [
            {
              "time": "09:00",
              "name": "Louvre",
              "category": "museum",
              "lat": 48.8606,
              "lon": 2.3376,
              "duration_min": 90,
              "cost_est": 20.0,
              "notes": "Pre-book tickets"
            }, ...
          ]
        }, ...
      ]
    }
    """
    if isinstance(itin, dict):
        # Assume already structured
        return itin

    # Fallback: convert plain text to a one-day, single-note plan
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

def itinerary_to_markdown(itin: dict) -> str:
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
            if cost is not None: meta.append(f"€{cost:.2f}")
            meta_txt = f" _({' • '.join(meta)})_" if meta else ""
            lines.append(f"- **{t}** — **{nm}**{meta_txt}")
            if notes:
                lines.append(f"  - {notes}")
        lines.append("")
    return "\n".join(lines)

def itinerary_to_json(itin: dict) -> str:
    return json.dumps(itin, ensure_ascii=False, indent=2)

def itinerary_to_ics(itin: dict, default_start="09:00"):
    # Minimal iCalendar export (one VEVENT per stop with time if available)
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
            # Convert HH:MM to HHMMSS
            tclean = t.replace(":", "") + "00"
            buf.write("BEGIN:VEVENT\n")
            buf.write(f"DTSTART:{yyyymmdd(day_str)}T{tclean}\n")
            buf.write(f"SUMMARY:{name}\n")
            if notes:
                # ICS lines must be folded at 75 chars; keep it simple:
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

    st.divider()
    st.subheader("Actions")
    gen_btn = st.button("✨ Generate Itinerary", type="primary")
    reset_btn = st.button("↺ Reset")

if reset_btn:
    st.session_state.clear()
    st.rerun()

# Maintain session state
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
            # Core fields you already had
            planner.set_city(city)
            planner.set_interests(", ".join(interests))

            # Optional advanced parameters — only if your planner supports them
            # Use try/except so UI never breaks if methods are missing.
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

            # Call your generator
            try:
                raw_itinerary = planner.create_itineary()  # keep your original method name
            except Exception as e:
                st.error(f"Planner error: {e}")
                raw_itinerary = "Unable to generate itinerary. Please adjust inputs and try again."

            itinerary = ensure_itinerary_dict(raw_itinerary)
            itinerary["city"] = city  # enforce
            # If multiple days requested and only one day returned, stretch dates
            if len(itinerary.get("days", [])) == 1 and trip_days > 1:
                # Add a day for each day of the trip
                base_day = itinerary["days"][0]
                itinerary["days"] = []
                for d in range(trip_days):
                    this_date = (start_date + timedelta(days=d)).isoformat()
                    clone = {
                        "date": this_date,
                        "summary": base_day.get("summary", ""),
                        "stops": base_day.get("stops", []),
                    }
                    itinerary["days"].append(clone)

            st.session_state["itinerary"] = itinerary

# ---------------------- Main content ----------------------
if st.session_state["itinerary"] is None:
    st.info("Start by entering your destination & interests in the sidebar, then click **Generate Itinerary**.")
    st.stop()

itin = st.session_state["itinerary"]

# Top KPIs
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("City", itin.get("city", "—"))
with col2:
    st.metric("Days", len(itin.get("days", [])))
with col3:
    total_stops = sum(len(d.get("stops", [])) for d in itin.get("days", []))
    st.metric("Stops", total_stops)
with col4:
    est_cost = 0.0
    for d in itin.get("days", []):
        for s in d.get("stops", []):
            c = s.get("cost_est")
            if isinstance(c, (int, float)): est_cost += c
    st.metric("Est. Total Cost", f"€{est_cost:,.0f}" if est_cost else "—")

# Tabs for different views
tab_overview, tab_map, tab_day, tab_export = st.tabs(["Overview", "Map", "Day-by-day", "Export"])

with tab_overview:
    st.subheader("🗒️ Overview")
    # Show a concise markdown summary
    st.markdown(itinerary_to_markdown(itin))

    # Editable table of all stops
    st.subheader("Edit Stops (All Days)")
    # Flatten for edit
    rows = []
    for di, d in enumerate(itin.get("days", [])):
        date_str = d.get("date", "")
        for si, s in enumerate(d.get("stops", [])):
            rows.append({
                "day_index": di,
                "stop_index": si,
                "date": date_str,
                "time": s.get("time", ""),
                "name": s.get("name", ""),
                "category": s.get("category", ""),
                "lat": s.get("lat"),
                "lon": s.get("lon"),
                "duration_min": s.get("duration_min"),
                "cost_est": s.get("cost_est"),
                "notes": s.get("notes", ""),
            })
    edited = st.data_editor(
        rows,
        num_rows="dynamic",
        use_container_width=True,
        key="all_stops_editor",
        column_config={
            "day_index": st.column_config.NumberColumn("Day#", disabled=True),
            "stop_index": st.column_config.NumberColumn("Stop#", disabled=True),
            "date": st.column_config.TextColumn("Date"),
            "time": st.column_config.TextColumn("Time (HH:MM)"),
            "name": st.column_config.TextColumn("Name"),
            "category": st.column_config.TextColumn("Category"),
            "lat": st.column_config.NumberColumn("Lat", format="%.6f"),
            "lon": st.column_config.NumberColumn("Lon", format="%.6f"),
            "duration_min": st.column_config.NumberColumn("Duration (min)"),
            "cost_est": st.column_config.NumberColumn("Cost (€)", format="%.2f"),
            "notes": st.column_config.TextColumn("Notes"),
        }
    )

    # Apply edits back into session itinerary
    if st.button("💾 Save Edits"):
        # Reset stops then rebuild from editor
        new_days = {}
        for r in edited:
            di = int(r["day_index"])
            if di not in new_days:
                # seed from original date/summary if exists
                old_day = itin["days"][di] if di < len(itin["days"]) else {"date": r.get("date",""), "summary":"", "stops":[]}
                new_days[di] = {"date": r.get("date", old_day.get("date","")),
                                "summary": old_day.get("summary",""),
                                "stops": []}
            stop = {
                "time": r.get("time") or "",
                "name": r.get("name") or "",
                "category": r.get("category") or "",
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "duration_min": r.get("duration_min"),
                "cost_est": r.get("cost_est"),
                "notes": r.get("notes") or "",
            }
            new_days[di]["stops"].append(stop)

        # Reassemble in original order
        new_itin_days = []
        for i in sorted(new_days.keys()):
            new_itin_days.append(new_days[i])
        st.session_state["itinerary"]["days"] = new_itin_days
        st.success("Edits saved.")

with tab_map:
    st.subheader("🗺️ Map")
    points = extract_points_for_map(itin)
    if not points:
        st.info("No geocoordinates found. Add lat/lon in the editor to see a map.")
    else:
        # Streamlit's native map
        st.map(points, latitude="lat", longitude="lon", size=10)
        with st.expander("Points shown"):
            st.dataframe(points, use_container_width=True)

with tab_day:
    st.subheader("📆 Day-by-day plan")
    for day in itin.get("days", []):
        with st.container(border=True):
            st.markdown(f"### {day.get('date','')}")
            if day.get("summary"): st.write(day["summary"])
            stops = day.get("stops", [])
            if not stops:
                st.caption("No stops for this day.")
                continue
            # Pretty list
            for s in stops:
                left, right = st.columns([2, 1])
                with left:
                    st.markdown(f"**{s.get('time','--:--')}** — **{s.get('name','Stop')}**")
                    meta = []
                    if s.get("category"): meta.append(s["category"])
                    if s.get("duration_min"): meta.append(f"{s['duration_min']} min")
                    if s.get("cost_est") is not None: meta.append(f"€{s['cost_est']:.2f}")
                    if meta:
                        st.caption(" • ".join(meta))
                    if s.get("notes"):
                        st.write(s["notes"])
                with right:
                    # Optional per-stop quick edits (not persisted until Save Edits in Overview)
                    st.text_input("Time", value=s.get("time",""), key=f"time_{day['date']}_{s.get('name','')}")
                    st.text_input("Notes", value=s.get("notes",""), key=f"notes_{day['date']}_{s.get('name','')}")

with tab_export:
    st.subheader("📤 Export")
    md = itinerary_to_markdown(itin)
    js = itinerary_to_json(itin)
    ics = itinerary_to_ics(itin, default_start=start_time.strftime("%H:%M"))

    st.download_button("Download Markdown", md, file_name="itinerary.md")
    st.download_button("Download JSON", js, file_name="itinerary.json")
    st.download_button("Download Calendar (.ics)", ics, file_name="itinerary.ics")

    st.divider()
    st.text_area("Preview (Markdown)", md, height=300)

# Footer tip
st.caption("Tip: Add lat/lon for each stop to unlock the map. Use the Overview → Edit Stops table to refine details.")
