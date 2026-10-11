"""Groq advice + deterministic emergency and booking gates.

Model output is advisory. It cannot create appointments or declare a photograph safe.
"""
import base64
import json
import os
import re

from groq import Groq


SPECIALTIES = ("General Medicine", "Neurology", "Orthopedics", "Gastroenterology", "Dermatology")
TERMS = {
    "Neurology": ("neurolog", "seizure", "migraine", "numbness"),
    "Orthopedics": ("orthop", "fracture", "broken bone", "joint injury", "sprain"),
    "Gastroenterology": ("gastro", "stomach ulcer", "gastric", "abdominal ulcer", "peptic ulcer"),
    "Dermatology": ("dermatolog", "skin rash", "eczema", "acne"),
}
EMERGENCY = re.compile(r"\b(chest pain|trouble breathing|can't breathe|cannot breathe|stroke|face droop|sudden weakness|uncontrolled bleeding|bleeding won't stop|suicid(?:e|al)|unconscious|severe head injury)\b", re.I)
PHOTO_WARNING = "A photo cannot establish injury severity. A clinician needs to assess it; seek urgent care for heavy bleeding, a deep wound, loss of feeling or movement, or signs of infection."
SYSTEM = """You are a clinic navigation assistant. Answer briefly in the user's language. Give cautious general self-care and safety measures; do not diagnose, prescribe, promise an outcome, or say an injury is safe from a photo. If serious or uncertain, recommend prompt in-person evaluation. Suggest one specialty from General Medicine, Neurology, Orthopedics, Gastroenterology, Dermatology. Never invent doctors, appointment times, treatment records or bookings. The application supplies those separately. Respond as JSON with keys advice (string), specialty (one of listed specialties), urgent (boolean)."""


def explicit_specialty(text: str):
    lower = text.lower()
    for specialty, keywords in TERMS.items():
        if any(word in lower for word in keywords):
            return specialty
    return None


def ask_groq(text: str, photo: bytes | None = None, mime: str | None = None):
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is not configured")
    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=20.0)
    content = text or "Describe any visible injury and advise a suitable clinic specialty."
    if photo:
        content = [{"type": "text", "text": content}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(photo).decode()}"}}]
    result = client.chat.completions.create(
        model=os.getenv("GROQ_VISION_MODEL" if photo else "GROQ_TEXT_MODEL", "qwen/qwen3.8-27b"),
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
        response_format={"type": "json_object"}, temperature=0.2, max_completion_tokens=350,
    )
    raw = result.choices[0].message.content or "{}"
    parsed = json.loads(raw)
    specialty = parsed.get("specialty")
    return {
        "advice": str(parsed.get("advice", "Please consult a clinician.")).strip()[:1800],
        "specialty": specialty if specialty in SPECIALTIES else "General Medicine",
        "urgent": parsed.get("urgent") is True,
    }


def assess(text: str, photo: bytes | None = None, mime: str | None = None):
    rule_emergency = bool(EMERGENCY.search(text))
    if rule_emergency:
        return {"advice": "Seek urgent in-person medical care now. Do not wait for an online booking. " + (PHOTO_WARNING if photo else ""), "specialty": "General Medicine", "urgent": True}
    result = ask_groq(text, photo, mime)
    result["specialty"] = explicit_specialty(text) or result["specialty"]
    result["urgent"] = result["urgent"]
    if photo:
        result["advice"] += " " + PHOTO_WARNING
    if result["urgent"]:
        result["advice"] = "Seek urgent in-person medical care now. " + result["advice"]
    return result
