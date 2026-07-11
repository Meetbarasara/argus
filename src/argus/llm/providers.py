"""The ONLY place that imports provider SDKs (05). Builds LangChain chat models by
provider name; agents/router stay provider-agnostic."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from argus.errors import LLMError


def build_chat_model(
    provider: str, model: str, api_key: str, *, temperature: float = 0.0
) -> BaseChatModel:
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=temperature)
    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=model, api_key=SecretStr(api_key), temperature=temperature)
    if provider == "cerebras":
        from langchain_cerebras import ChatCerebras

        return ChatCerebras(model=model, api_key=SecretStr(api_key), temperature=temperature)
    raise LLMError(f"unknown provider: {provider}")
