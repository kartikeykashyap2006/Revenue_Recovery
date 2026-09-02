#!/usr/bin/env python3
"""One-off diagnostic: makes a single raw Gemini API call and prints the
full response JSON, so we can see exactly what's coming back (finish
reason, token usage, whether 'parts' is empty, etc.) instead of guessing
from the swallowed error in the pipeline's try/except."""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

if not settings.GEMINI_API_KEY:
    print("GEMINI_API_KEY is not set in .env -- nothing to test.")
    sys.exit(1)

url = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
)
payload = json.dumps({
    "contents": [{"role": "user", "parts": [{"text": "Reply with strict JSON only, nothing else: {\"action\": \"proceed\", \"confidence\": 0.9, \"reasoning\": \"test\"}"}]}],
    "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.2},
}).encode()

print(f"Calling model: {settings.GEMINI_MODEL}")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code} error:")
    print(e.read().decode())
    sys.exit(1)

data = json.loads(raw)
print(json.dumps(data, indent=2))

parts = data["candidates"][0]["content"]["parts"]
answer = "".join(p.get("text", "") for p in parts if not p.get("thought"))
print("\n--- extracted non-thought answer ---")
print(answer if answer else "(empty -- still no real answer, needs an even higher max_tokens)")
print(f"thoughtsTokenCount: {data.get('usageMetadata', {}).get('thoughtsTokenCount')}")
print(f"finishReason: {data['candidates'][0].get('finishReason')}")
