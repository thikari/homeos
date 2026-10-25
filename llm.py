#!/usr/bin/env python3
"""Ein Aufruf für alle KI-Funktionen (Kassenzettel, Foto-Erkennung, Sprach-Zerlegung).

Anbieter nach vorhandenem Schlüssel: MISTRAL_API_KEY (bevorzugt) → Mistral; sonst ANTHROPIC_API_KEY → Claude.
Modelle: MISTRAL_MODEL (Standard mistral-small-latest, kann Bilder), TAFEL_VISION_MODEL (Claude, Standard claude-haiku-5-5).
    frage(prompt, image_b64=None, max_tokens=800) → Text (bei JSON-Aufgaben: der Prompt verlangt JSON, der Aufrufer parst)
"""
import os, json, urllib.request, urllib.error

def anbieter():
    if os.environ.get("MISTRAL_API_KEY", "").strip():
        return "mistral"
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    return None

def fehlt():
    return "KI ist nicht eingerichtet – MISTRAL_API_KEY (oder ANTHROPIC_API_KEY) in Railway setzen."

def frage(prompt, image_b64=None, max_tokens=800, json_mode=True):
    a = anbieter()
    if a == "mistral":
        key = os.environ["MISTRAL_API_KEY"].strip()
        content = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}})
        body = {"model": os.environ.get("MISTRAL_MODEL", "mistral-small-latest"), "max_tokens": max_tokens, "temperature": 0,
                "messages": [{"role": "user", "content": content}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.load(r)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")
            import re as _re
            msg = _re.sub(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", "<bild>", msg)
            raise RuntimeError(f"Mistral {e.code}: {msg[:400]}")
        return j["choices"][0]["message"]["content"]
    if a == "anthropic":
        key = os.environ["ANTHROPIC_API_KEY"].strip()
        content = []
        if image_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        content.append({"type": "text", "text": prompt})
        body = {"model": os.environ.get("TAFEL_VISION_MODEL", "claude-haiku-5-5"), "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.load(r)
        return "".join(c.get("text", "") for c in j.get("content", []))
    raise RuntimeError(fehlt())

def json_aus(text, start="{", end="}"):
    """Erstes JSON-Objekt/-Array aus einer Antwort ziehen (auch wenn Text drumherum steht)."""
    i, k = text.find(start), text.rfind(end)
    return json.loads(text[i:k + 1]) if i >= 0 and k > i else None
