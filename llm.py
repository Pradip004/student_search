import json
import requests
from django.db.models import Q
from records.models import Person

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"   # change to the exact name shown by: ollama list

# Fields the AI is allowed to filter on
FIELDS = {
    "person_type": "iexact",
    "name": "icontains",
    "department": "icontains",
    "course": "icontains",
    "year": "exact",
    "designation": "icontains",
    "status": "iexact",
}

PROMPT = """You convert a search request into JSON filters.
Allowed keys: person_type (student, candidate, or employee), name, department,
course, year (a number), designation, status.
Return ONLY a JSON object. Leave out keys that are not mentioned.
Request: {q}"""


def ask_ai(query):
    """Ask Gemma to turn a sentence into filters. Returns {} if it fails."""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": PROMPT.format(q=query),
                  "format": "json", "stream": False},
            timeout=60,
        )
        data = json.loads(r.json()["response"])
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key, value in data.items():
        if key in FIELDS and value not in (None, "", []):
            clean[key] = str(value).strip()
    return clean


def build_queryset(filters):
    """Turn saved filters into a safe database query."""
    if "_keyword" in filters:
        q = filters["_keyword"]
        return Person.objects.filter(
            Q(name__icontains=q) | Q(department__icontains=q) |
            Q(course__icontains=q) | Q(designation__icontains=q)
        )
    conditions = {}
    for key, value in filters.items():
        if key not in FIELDS:
            continue
        if key == "year":
            try:
                value = int(value)
            except ValueError:
                continue
        lookup = key if FIELDS[key] == "exact" else f"{key}__{FIELDS[key]}"
        conditions[lookup] = value
    return Person.objects.filter(**conditions)