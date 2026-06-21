"""Quick LLM connectivity test — run this to diagnose API issues without launching the browser."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx


async def test_openai():
    api_key = os.getenv("LLM_API_KEY", "")
    model = "gpt-4o-mini"

    if not api_key:
        print("ERROR: LLM_API_KEY not found in .env")
        return

    print(f"Provider : openai")
    print(f"Model    : {model}")
    print(f"Key prefix: {api_key[:20]}...")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "Say OK"}],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    print(f"HTTP status: {response.status_code}")

    if response.is_success:
        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()
        print(f"\nSUCCESS — model replied: {text}")
    else:
        print(f"Response body: {response.text}")
        print("\nFAILED — see body above for the exact API error")


asyncio.run(test_openai())
