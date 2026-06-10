"""Environment-driven configuration and the provider switch (OpenAI now, Azure later).

Everything that depends on "which LLM provider" funnels through here, so the rest of
the codebase never hardcodes OpenAI vs Azure. Flip PROVIDER in .env and the whole app
moves to Azure in Phase B without touching feature code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """All runtime configuration, read from the project-root .env (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- provider switch ---
    provider: str = "openai"  # "openai" (Phase A) or "azure" (Phase B)

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"

    # --- Azure OpenAI (Phase B) ---
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = ""
    azure_openai_embed_deployment: str = ""

    # --- Langfuse (observability) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- paths ---
    db_path: Path = ROOT / "data" / "db" / "sales.sqlite"
    docs_dir: Path = ROOT / "data" / "docs"
    chroma_dir: Path = ROOT / "data" / "chroma"
    charts_dir: Path = ROOT / "data" / "charts"
    out_dir: Path = ROOT / "data" / "out"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def is_azure(self) -> bool:
        return self.provider.lower() == "azure"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so we parse .env once."""
    return Settings()


# Cap output tokens per call: the report's structured sections are small, so this bounds
# worst-case cost without truncating legitimate output. Overridable via kwargs.
_MAX_OUTPUT_TOKENS = 2000


def get_chat_model(temperature: float = 0.2, **kwargs):
    """Return a LangChain chat model for the configured provider."""
    s = get_settings()
    kwargs.setdefault("max_tokens", _MAX_OUTPUT_TOKENS)
    if s.is_azure:
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=s.azure_openai_chat_deployment,
            azure_endpoint=s.azure_openai_endpoint,
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
            temperature=temperature,
            **kwargs,
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=s.openai_chat_model,
        api_key=s.openai_api_key,
        temperature=temperature,
        **kwargs,
    )


def get_embeddings():
    """Return a LangChain embeddings model for the configured provider."""
    s = get_settings()
    if s.is_azure:
        from langchain_openai import AzureOpenAIEmbeddings

        return AzureOpenAIEmbeddings(
            azure_deployment=s.azure_openai_embed_deployment,
            azure_endpoint=s.azure_openai_endpoint,
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
        )
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=s.openai_embed_model, api_key=s.openai_api_key)
