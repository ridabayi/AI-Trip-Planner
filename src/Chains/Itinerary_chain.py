<<<<<<< HEAD
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.Config.config import GROQ_API_KEY


llm = ChatGroq(
    groq_api_key = GROQ_API_KEY,
    model_name = "llama-3.3-70b-versatile",
    temperature=0.3
)


itnineary_prompt = ChatPromptTemplate([
    ("system" , "You are a helpful travel asssistant. Create a day trip itineary for {city} based on user's interest : {interests}. Provide a brief , bulleted itineary"),
    ("human" , "Create a itineary for my day trip")
])

def generate_itineary(city:str , interests:list[str]) -> str:
    response = llm.invoke(
        itnineary_prompt.format_messages(city=city,interests=', '.join(interests))
    )

    return response.content
=======
# src/Chains/itinerary_agent.py
from typing import List, Dict, Any
import json
import urllib.parse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from src.Config.config import GROQ_API_KEY

# ======================= LLM =======================
llm = ChatGroq(
    groq_api_key=GROQ_API_KEY,
    model_name="llama-3.3-70b-versatile",
    temperature=0.2,                      # réponses nettes
    model_kwargs={"top_p": 0.9}           # supprime le warning Pydantic
)

# ==================== Prompt sécurisé ====================
# On injecte l'exemple JSON via une variable "schema" pour éviter d'échapper les accolades.
schema_example = (
    '{'
    '"language_code": "fr|en|es|ar|...", '
    '"overview": "string", '
    '"morning": ["bullet1"], '
    '"lunch": ["bullet1"], '
    '"afternoon": ["bullet1"], '
    '"evening": ["bullet1"], '
    '"logistics": ["bullet1"], '
    '"rain_plan": ["bullet1"], '
    '"recap": ["bullet1"], '
    '"pois": ['
      '{"name":"string","address":"string","category":"sight|museum|food|view|park","est_cost_eur": 0}'
    ']'
    '}'
)

itinerary_json_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "Tu es un expert du voyage. Tu DOIS détecter la langue du dernier message utilisateur "
     "et répondre uniquement dans cette langue. Renvoie STRICTEMENT un JSON (sans texte autour). "
     "Structure attendue : {schema}"),
    ("human",
     "City: {city}\nInterests: {interests}\n"
     "Contraintes : 6–10 POIs max, adresses ou lieux reconnaissables. "
     "Brefs bullets, concrets (horaires indicatifs, ordre logique).")
]).partial(schema=schema_example)

chain_json = itinerary_json_prompt | llm | StrOutputParser()

# =================== Helpers Google Maps ===================
def _q(s: str) -> str:
    return urllib.parse.quote_plus((s or "").strip())

def build_search_link(label: str, address: str = "") -> str:
    q = f"{label}, {address}" if address else label
    return f"https://www.google.com/maps/search/?api=1&query={_q(q)}"

def build_dir_link(points: List[str], mode: str = "walking") -> str:
    """
    Construit un lien /dir/ Google Maps avec waypoints.
    mode: walking | bicycling | driving | transit
    """
    pts = [p for p in points if p and p.strip()]
    if not pts:
        return ""
    if len(pts) == 1:
        return build_search_link(pts[0])
    path = "/".join(_q(p) for p in pts)
    return f"https://www.google.com/maps/dir/{path}?travelmode={_q(mode)}"

# =================== Localisation des titres ===================
def _headings(lang: str) -> Dict[str, str]:
    l = (lang or "fr").lower()
    if l.startswith("en"):
        return {"overview": "## Overview","morning": "## Morning","lunch": "## Lunch",
                "afternoon": "## Afternoon","evening": "## Evening","logistics": "## Logistics",
                "rain_plan": "## Plan B (weather)","recap": "## Recap","maps": "## Maps",
                "route_walk": "Walking route"}
    if l.startswith("es"):
        return {"overview": "## Resumen","morning": "## Mañana","lunch": "## Almuerzo",
                "afternoon": "## Tarde","evening": "## Noche","logistics": "## Logística",
                "rain_plan": "## Plan B (clima)","recap": "## Resumen","maps": "## Mapas",
                "route_walk": "Ruta a pie"}
    if l.startswith("ar"):
        return {"overview": "## نظرة عامة","morning": "## الصباح","lunch": "## الغداء",
                "afternoon": "## بعد الظهر","evening": "## المساء","logistics": "## الجوانب اللوجستية",
                "rain_plan": "## الخطة البديلة (الطقس)","recap": "## خلاصة","maps": "## الخرائط",
                "route_walk": "مسار سير"}
    # FR par défaut
    return {"overview": "## Aperçu","morning": "## Matin","lunch": "## Midi",
            "afternoon": "## Après-midi","evening": "## Soir","logistics": "## Logistique",
            "rain_plan": "## Plan B (météo)","recap": "## Récap","maps": "## Cartes",
            "route_walk": "Itinéraire à pied"}

# =================== Parsing/formatage ===================
def _safe_json(s: str) -> Dict[str, Any]:
    """
    Coupe proprement si le modèle a ajouté du texte avant/après le JSON.
    """
    s = (s or "").strip()
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j+1]
    return json.loads(s)

def _bullets(xs: List[str]) -> str:
    xs = xs or []
    return "\n".join(f"- {x}" for x in xs)

# =================== API publique ===================
@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.8, min=1, max=6),
    retry=retry_if_exception_type(Exception)
)
def generate_itinerary_payload(city: str, interests: List[str], transport_mode: str = "walking") -> Dict[str, Any]:
    """
    Génère un payload structuré:
    {
      "language_code": "fr|en|...",
      "sections": {...},
      "pois": [{"label","address","map_link","category","est_cost_eur"}],
      "maps": {"dir_link","transport_mode"},
      "markdown": "...."
    }
    """
    interests_txt = ", ".join([i.strip() for i in interests if i and i.strip()]) or "general"
    raw = chain_json.invoke({"city": city, "interests": interests_txt})
    data = _safe_json(raw)

    # POIs + liens
    pois_in = data.get("pois", []) or []
    points = [(p.get("address") or p.get("name") or "").strip() for p in pois_in]
    dir_link = build_dir_link(points, mode=transport_mode)

    pois_out = []
    for p in pois_in:
        label = p.get("name") or p.get("address") or "POI"
        addr = p.get("address") or ""
        pois_out.append({
            "label": label,
            "address": addr,
            "map_link": build_search_link(label, addr),
            "category": p.get("category"),
            "est_cost_eur": p.get("est_cost_eur"),
        })

    # Markdown localisé
    lang = (data.get("language_code") or "fr").lower()
    H = _headings(lang)
    md_parts = [
        f"{H['overview']}\n{data.get('overview','')}\n",
        f"{H['morning']}\n{_bullets(data.get('morning'))}\n",
        f"{H['lunch']}\n{_bullets(data.get('lunch'))}\n",
        f"{H['afternoon']}\n{_bullets(data.get('afternoon'))}\n",
        f"{H['evening']}\n{_bullets(data.get('evening'))}\n",
        f"{H['logistics']}\n{_bullets(data.get('logistics'))}\n",
        f"{H['rain_plan']}\n{_bullets(data.get('rain_plan'))}\n",
        f"{H['recap']}\n{_bullets(data.get('recap'))}\n",
        f"{H['maps']}\n- {H['route_walk']}" + (f" • [Ouvrir]({dir_link})" if dir_link else "")
    ]
    for p in pois_out:
        line = f"- {p['label']}" + (f" — {p['address']}" if p['address'] else "") + f" • [Carte]({p['map_link']})"
        md_parts.append(line)
    markdown = "\n".join(md_parts)

    return {
        "language_code": data.get("language_code") or "fr",
        "sections": {
            "overview": data.get("overview", ""),
            "morning": data.get("morning", []),
            "lunch": data.get("lunch", []),
            "afternoon": data.get("afternoon", []),
            "evening": data.get("evening", []),
            "logistics": data.get("logistics", []),
            "rain_plan": data.get("rain_plan", []),
            "recap": data.get("recap", [])
        },
        "pois": pois_out,
        "maps": {
            "dir_link": dir_link,
            "transport_mode": transport_mode
        },
        "markdown": markdown
    }

def generate_itinerary_markdown(city: str, interests: List[str], transport_mode: str = "walking") -> str:
    """Raccourci : renvoie directement le Markdown."""
    payload = generate_itinerary_payload(city, interests, transport_mode)
    return payload["markdown"]
>>>>>>> bf39601136ce8923cfbc7e0af62dfcd38c3f6192
