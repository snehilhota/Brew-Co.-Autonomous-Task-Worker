"""Make one Gemini API connectivity check"""

import os

import httpx
from dotenv import load_dotenv

def main() -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is missing from .env")
    model = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
    url = "https://generativelanguage.googleapis.com/v1beta/interactions"

    headers = {"x-goog-api-key" : api_key}
    payload = {
        "model" : model,
        "input" : "Reply with exactly: GEMINI_API_CONNECTED",
        "store" : False
    }

    response = httpx.post(url, headers=headers, json=payload, timeout=30.0)

    if response.is_error:
        print(f"Gemini returned HTTP {response.status_code}:")
        print(response.text)
        raise SystemExit("The Gemini hello call failed")

    result = response.json()
    answer = result["steps"][-1]["content"][0]["text"]
    
    print("Gemini replied:", answer)
    print("LLM HELLO CALL PASSED")

if __name__ == "__main__":
    main()