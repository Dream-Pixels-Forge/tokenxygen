"""Multi-provider support — route to OpenAI, Anthropic, Google, or local Ollama.

The provider layer normalizes different API formats into a single interface,
allowing Tokenxygen to seamlessly switch between providers based on cost/quality.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"


@dataclass
class ProviderConfig:
    """Configuration for a single provider."""

    provider: Provider
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_context: int = 128_000
    supports_streaming: bool = True
    supports_system: bool = True
    enabled: bool = True

    @property
    def cost_per_token_input(self) -> float:
        return self.cost_per_1k_input / 1000

    @property
    def cost_per_token_output(self) -> float:
        return self.cost_per_1k_output / 1000


# Pre-configured models
MODEL_REGISTRY: dict[str, ProviderConfig] = {
    # OpenAI
    "gpt-4o": ProviderConfig(
        provider=Provider.OPENAI,
        model="gpt-4o",
        cost_per_1k_input=2.50,
        cost_per_1k_output=10.00,
        max_context=128_000,
    ),
    "gpt-4o-mini": ProviderConfig(
        provider=Provider.OPENAI,
        model="gpt-4o-mini",
        cost_per_1k_input=0.15,
        cost_per_1k_output=0.60,
        max_context=128_000,
    ),
    "gpt-4-turbo": ProviderConfig(
        provider=Provider.OPENAI,
        model="gpt-4-turbo",
        cost_per_1k_input=10.00,
        cost_per_1k_output=30.00,
        max_context=128_000,
    ),
    # Anthropic
    "claude-3.5-sonnet": ProviderConfig(
        provider=Provider.ANTHROPIC,
        model="claude-3-5-sonnet-20241022",
        cost_per_1k_input=3.00,
        cost_per_1k_output=15.00,
        max_context=200_000,
    ),
    "claude-3-haiku": ProviderConfig(
        provider=Provider.ANTHROPIC,
        model="claude-3-haiku-20240307",
        cost_per_1k_input=0.25,
        cost_per_1k_output=1.25,
        max_context=200_000,
    ),
    "claude-3-opus": ProviderConfig(
        provider=Provider.ANTHROPIC,
        model="claude-3-opus-20240229",
        cost_per_1k_input=15.00,
        cost_per_1k_output=75.00,
        max_context=200_000,
    ),
    # Google
    "gemini-1.5-pro": ProviderConfig(
        provider=Provider.GOOGLE,
        model="gemini-1.5-pro",
        cost_per_1k_input=3.50,
        cost_per_1k_output=10.50,
        max_context=2_000_000,
    ),
    "gemini-1.5-flash": ProviderConfig(
        provider=Provider.GOOGLE,
        model="gemini-1.5-flash",
        cost_per_1k_input=0.075,
        cost_per_1k_output=0.30,
        max_context=1_000_000,
    ),
    # Ollama (local, free)
    "llama3.1": ProviderConfig(
        provider=Provider.OLLAMA,
        model="llama3.1",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=128_000,
    ),
    "codellama": ProviderConfig(
        provider=Provider.OLLAMA,
        model="codellama",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=16_000,
    ),
    "deepseek-coder": ProviderConfig(
        provider=Provider.OLLAMA,
        model="deepseek-coder:6.7b",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=16_000,
    ),
}


@dataclass
class NormalizedMessage:
    """Normalized message format across providers."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class NormalizedRequest:
    """Normalized request format across providers."""

    model: str
    messages: list[NormalizedMessage]
    max_tokens: int = 4096
    temperature: float = 0.7
    stream: bool = False


@dataclass
class NormalizedResponse:
    """Normalized response format across providers."""

    content: str
    model: str
    provider: Provider
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Base class for provider adapters."""

    @abstractmethod
    def to_api_format(self, request: NormalizedRequest) -> dict:
        """Convert normalized request to provider API format."""
        ...

    @abstractmethod
    def from_api_response(self, response: dict, model: str) -> NormalizedResponse:
        """Convert provider response to normalized format."""
        ...

    @abstractmethod
    def get_base_url(self) -> str:
        """Get the provider's API base URL."""
        ...

    @abstractmethod
    def get_headers(self, api_key: str) -> dict:
        """Get headers for API requests."""
        ...

    @abstractmethod
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD for given token counts."""
        ...


class OpenAIAdapter(ProviderAdapter):
    """OpenAI / OpenAI-compatible adapter."""

    def to_api_format(self, request: NormalizedRequest) -> dict:
        messages = []
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream,
        }

    def from_api_response(self, response: dict, model: str) -> NormalizedResponse:
        choice = response.get("choices", [{}])[0]
        usage = response.get("usage", {})

        return NormalizedResponse(
            content=choice.get("message", {}).get("content", ""),
            model=response.get("model", model),
            provider=Provider.OPENAI,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=response,
        )

    def get_base_url(self) -> str:
        return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        config = MODEL_REGISTRY.get("gpt-4o")
        return (input_tokens * config.cost_per_token_input +
                output_tokens * config.cost_per_token_output)


class AnthropicAdapter(ProviderAdapter):
    """Anthropic Claude adapter."""

    def to_api_format(self, request: NormalizedRequest) -> dict:
        system = ""
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        result = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if system:
            result["system"] = system
        return result

    def from_api_response(self, response: dict, model: str) -> NormalizedResponse:
        content = ""
        for block in response.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage = response.get("usage", {})

        return NormalizedResponse(
            content=content,
            model=response.get("model", model),
            provider=Provider.ANTHROPIC,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            finish_reason=response.get("stop_reason", "stop"),
            raw=response,
        )

    def get_base_url(self) -> str:
        return "https://api.anthropic.com/v1"

    def get_headers(self, api_key: str) -> dict:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        config = MODEL_REGISTRY.get("claude-3.5-sonnet")
        return (input_tokens * config.cost_per_token_input +
                output_tokens * config.cost_per_token_output)


class OllamaAdapter(ProviderAdapter):
    """Ollama local model adapter."""

    def to_api_format(self, request: NormalizedRequest) -> dict:
        messages = []
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return {
            "model": request.model,
            "messages": messages,
            "stream": request.stream,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

    def from_api_response(self, response: dict, model: str) -> NormalizedResponse:
        message = response.get("message", {})
        return NormalizedResponse(
            content=message.get("content", ""),
            model=response.get("model", model),
            provider=Provider.OLLAMA,
            input_tokens=response.get("prompt_eval_count", 0),
            output_tokens=response.get("eval_count", 0),
            cost_usd=0.0,  # Local is free
            finish_reason="stop",
            raw=response,
        )

    def get_base_url(self) -> str:
        return os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def get_headers(self, api_key: str) -> dict:
        return {"Content-Type": "application/json"}

    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0  # Local is free


# Adapter registry
ADAPTERS: dict[Provider, ProviderAdapter] = {
    Provider.OPENAI: OpenAIAdapter(),
    Provider.ANTHROPIC: AnthropicAdapter(),
    Provider.OLLAMA: OllamaAdapter(),
}


def get_adapter(provider: Provider) -> ProviderAdapter:
    """Get the adapter for a provider."""
    return ADAPTERS[provider]


def get_cheapest_provider(
    token_count: int,
    require_system: bool = True,
    exclude: list[Provider] | None = None,
) -> tuple[Provider, str, float]:
    """Find the cheapest provider for a given token count.

    Returns (provider, model, cost).
    """
    exclude = exclude or []
    candidates = []

    for model_name, config in MODEL_REGISTRY.items():
        if not config.enabled:
            continue
        if config.provider in exclude:
            continue
        if require_system and not config.supports_system:
            continue
        if token_count > config.max_context:
            continue

        cost = config.cost_per_token_input * token_count
        candidates.append((config.provider, model_name, cost))

    if not candidates:
        # Fallback to OpenAI
        return Provider.OPENAI, "gpt-4o", 0.0

    candidates.sort(key=lambda x: x[2])
    return candidates[0]
