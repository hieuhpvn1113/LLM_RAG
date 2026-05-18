# llm/client.py — Groq LLM client (sync + async)
from groq import Groq, AsyncGroq
from config import GROQ_API_KEY, LLM_MODEL


class LLMClient:
    """Sync client — dùng cho CLI / script thường."""

    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY)
        self.model  = LLM_MODEL

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return response.choices[0].message.content


class AsyncLLMClient:
    """Async client — dùng trong ingestor pipeline (asyncio)."""

    def __init__(self):
        self.client = AsyncGroq(api_key=GROQ_API_KEY)
        self.model  = LLM_MODEL

    async def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return response.choices[0].message.content
