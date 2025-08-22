from datetime import date, timedelta
from typing import Optional, Dict, Any, List, Union
from langchain_core.messages import HumanMessage, AIMessage
from src.Chains.Itinerary_chain import generate_itineary
from src.Utils.logger import get_logger
from src.Utils.custom_exception import CustomException
import re

logger = get_logger(__name__)

class TravelPlanner:
    def __init__(self):
        self.messages: List[Union[HumanMessage, AIMessage]] = []
        self.city: str = ""
        self.interests: List[str] = []
        self.itineary: Union[str, Dict[str, Any]] = ""
        # NEW:
        self.trip_days: int = 1
        self.start_date: date = date.today()
        self.preferences: Dict[str, Any] = {}

        logger.info("Initialized TravelPlanner instance")

    # ---------- setters ----------
    def set_city(self, city: str):
        try:
            self.city = city
            self.messages.append(HumanMessage(content=city))
            logger.info("City set successfully")
        except Exception as e:
            logger.error(f"Error while setting city: {e}")
            raise CustomException("Failed to set city", e)

    def set_interests(self, interests_str: str):
        try:
            self.interests = [i.strip() for i in interests_str.split(",") if i.strip()]
            self.messages.append(HumanMessage(content=interests_str))
            logger.info("Interests set successfully")
        except Exception as e:
            logger.error(f"Error while setting interests: {e}")
            raise CustomException("Failed to set interests", e)

    # NEW: optional controls used by your Streamlit UI
    def set_days(self, days: int):
        try:
            self.trip_days = max(1, int(days))
        except Exception as e:
            logger.error(f"Error while setting days: {e}")
            raise CustomException("Failed to set days", e)

    def set_start_date(self, start_date_str: str):
        try:
            y, m, d = map(int, start_date_str.split("-"))
            self.start_date = date(y, m, d)
        except Exception as e:
            logger.error(f"Error while setting start_date: {e}")
            raise CustomException("Failed to set start_date", e)

    def set_preferences(self, prefs: Dict[str, Any]):
        try:
            self.preferences = prefs or {}
        except Exception as e:
            logger.error(f"Error while setting preferences: {e}")
            raise CustomException("Failed to set preferences", e)

    # ---------- helpers ----------
    def _text_to_stops(self, text: str) -> List[Dict[str, Any]]:
        """
        Heuristic: split lines, try to capture times, build simple stop rows.
        Works with bullet/numbered lists or plain paragraphs.
        """
        lines = [l.strip("•-–— ").strip() for l in text.splitlines() if l.strip()]
        stops: List[Dict[str, Any]] = []
        for l in lines:
            # Capture 09:00 / 9:00 AM / 9 AM patterns
            m = re.search(r'(\b\d{1,2}(:\d{2})?\s*(AM|PM)?\b)', l, flags=re.I)
            t = m.group(1) if m else ""
            name = l.split(":")[0][:60] if ":" in l else (l[:60] or "Stop")
            stops.append({
                "time": t,
                "name": name,
                "category": "general",
                "lat": None, "lon": None,
                "duration_min": None,
                "cost_est": None,
                "notes": l
            })
        if not stops:
            stops = [{
                "time": "09:00",
                "name": "Your plan",
                "category": "general",
                "lat": None, "lon": None,
                "duration_min": None,
                "cost_est": None,
                "notes": text
            }]
        return stops

    def _normalize_day_payload(self, raw_day: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Accept dict (must contain 'stops') or string (parse into stops).
        """
        if isinstance(raw_day, dict):
            raw_day.setdefault("summary", "")
            raw_day.setdefault("stops", [])
            return raw_day
        return {
            "summary": "Generated itinerary",
            "stops": self._text_to_stops(raw_day)
        }

    # Themes to avoid repeating the same plan every day
    def _day_theme(self, idx: int) -> str:
        pool = [
            "museums & landmarks",
            "neighborhoods & hidden gems",
            "parks & outdoors",
            "food & markets",
            "architecture & photography spots",
            "family-friendly activities",
            "nightlife & entertainment",
        ]
        return pool[idx % len(pool)]

    # ---------- main ----------
    def create_itineary(self):
        try:
            if not self.city or not self.interests:
                raise ValueError("City and interests must be set before creating an itinerary.")

            logger.info(
                f"Generating itinerary | city={self.city} | interests={self.interests} | "
                f"days={self.trip_days} | start_date={self.start_date}"
            )

            # Build one day at a time so each day can be different
            days_payload: List[Dict[str, Any]] = []

            for d in range(self.trip_days):
                the_date = (self.start_date + timedelta(days=d)).isoformat()
                theme = self._day_theme(d)

                # Mix user's interests with the day's theme
                day_interests = list(dict.fromkeys(self.interests + [theme]))  # keep order, deduplicate

                # Call your existing chain. Signature is (city, interests).
                # We vary interests by day to force different content.
                raw = generate_itineary(self.city, day_interests)

                # If your chain ever returns a full itinerary dict with "days", return it as-is.
                if isinstance(raw, dict) and "days" in raw:
                    self.itineary = raw
                    self.messages.append(AIMessage(content=str(raw)))
                    logger.info("Itinerary generated (structured multi-day) successfully")
                    return raw

                day_obj = self._normalize_day_payload(raw)
                days_payload.append({
                    "date": the_date,
                    "summary": f"Day {d+1}: Focus on {theme}",
                    "stops": day_obj.get("stops", [])
                })

            itinerary = {
                "city": self.city,
                "days": days_payload
            }

            self.itineary = itinerary
            self.messages.append(AIMessage(content=str(itinerary)))
            logger.info("Itinerary generated (normalized per-day) successfully")
            return itinerary

        except Exception as e:
            logger.error(f"Error while creating itinerary: {e}")
            raise CustomException("Failed to create itinerary", e)
