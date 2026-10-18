"""Models exposed by a saved account and compatible with our text call runtime."""

import httpx
from fastapi import HTTPException


def supported_chat_model(provider, model):
    if not isinstance(model, str):
        return False
    if provider == "openai":
        return model.startswith(("gpt-4.1", "gpt-4o", "gpt-3.5-turbo")) and not any(
            part in model
            for part in ("audio", "realtime", "search", "transcribe", "tts")
        )
    if provider == "groq":
        return model.startswith(
            ("llama-", "meta-llama/", "qwen/", "openai/gpt-oss-", "moonshotai/")
        ) and not any(
            part in model.lower() for part in ("guard", "safeguard", "prompt-guard")
        )
    return False


async def list_chat_models(provider, api_key):
    urls = {
        "groq": "https://api.groq.com/openai/v1/models",
        "openai": "https://api.openai.com/v1/models",
    }
    if provider not in urls:
        raise HTTPException(
            422, "Choose a Groq or OpenAI connection for language models"
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                urls[provider], headers={"Authorization": f"Bearer {api_key}"}
            )
        if response.status_code in (401, 403):
            raise HTTPException(
                422,
                "This connection cannot list models. Check its API key and permissions in Connections.",
            )
        if not response.is_success:
            raise HTTPException(
                502, "The provider could not load models. Try again shortly."
            )
        data = response.json()["data"]
        if not isinstance(data, list):
            raise ValueError("Invalid catalog")
        return sorted(
            {
                item["id"]
                for item in data
                if isinstance(item, dict)
                and item.get("active", True)
                and supported_chat_model(provider, item.get("id"))
            }
        )
    except (httpx.RequestError, ValueError, KeyError, TypeError):
        raise HTTPException(
            502,
            "Could not load models from the provider. Check the connection and retry.",
        )
