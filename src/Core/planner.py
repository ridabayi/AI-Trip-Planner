# src/Core/planner.py
from datetime import date, timedelta
from typing import Optional, Dict, Any, List, Union
from langchain_core.messages import HumanMessage, AIMessage
from src.Utils.logger import get_logger
from src.Utils.custom_exception import CustomException
from src.Chains.Itinerary_chain import generate_itinerary_payload

logger = get_logger(__name__)

class TravelPlanner:
    def __init__(self):
        self.messages: List[Union[HumanMessage, AIMessage]] = []
        self.city: str = ""
        self.interests: List[str] = []
        self.itinerary: Union[str, Dict[str, Any]] = ""
        self.trip_days: int = 1
        self.start_date: date = date.today()
        self.preferences: Dict[str, Any] = {}
        self.transport_mode: str = "walking"
        logger.info("Initialized TravelPlanner instance")

    # ---------- setters ----------
    def set_city(self, city: str):
        try:
            self.city = city.strip()
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

    def set_transport_mode(self, mode: str):
        try:
            mode = (mode or "").lower().strip()
            if mode not in {"walking", "bicycling", "driving", "transit"}:
                raise ValueError("Invalid transport mode")
            self.transport_mode = mode
        except Exception as e:
            logger.error(f"Error while setting transport_mode: {e}")
            raise CustomException("Failed to set transport_mode", e)

    # ---------- helpers ----------
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
    def create_itinerary(self):
        try:
            if not self.city or not self.interests:
                raise ValueError("City and interests must be set before creating an itinerary.")

            logger.info(
                f"Generating itinerary | city={self.city} | interests={self.interests} | "
                f"days={self.trip_days} | start_date={self.start_date} | mode={self.transport_mode}"
            )

            days_payload: List[Dict[str, Any]] = []
            all_markdown: List[str] = []
            language_code: Optional[str] = None

            for d in range(self.trip_days):
                the_date = (self.start_date + timedelta(days=d)).isoformat()
                theme = self._day_theme(d)
                day_interests = list(dict.fromkeys(self.interests + [theme]))

                payload = generate_itinerary_payload(
                    city=self.city,
                    interests=day_interests,
                    transport_mode=self.transport_mode
                )

                language_code = language_code or payload.get("language_code", "fr")
                markdown = payload.get("markdown", "")
                sections = payload.get("sections", {}) or {}
                pois = payload.get("pois", []) or []
                maps = payload.get("maps", {}) or {}

                days_payload.append({
                    "date": the_date,
                    "theme": theme,
                    "sections": sections,
                    "pois": pois,
                    "maps": maps
                })

                title = f"# Jour {d+1} — {the_date}"
                all_markdown.append(f"{title}\n\n{markdown}\n")

            itinerary = {
                "city": self.city,
                "language_code": language_code or "fr",
                "days": days_payload,
                "markdown": "\n---\n".join(all_markdown)
            }

            self.itinerary = itinerary
            self.messages.append(AIMessage(content=str(itinerary)))
            logger.info("Itinerary generated successfully (multilang + maps)")
            return itinerary

        except Exception as e:
            logger.error(f"Error while creating itinerary: {e}")
            raise CustomException("Failed to create itinerary", e)

    # Compat nom historique
    def create_itineary(self):
        return self.create_itinerary()
