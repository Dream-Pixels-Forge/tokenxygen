"""Tests for multi-provider support."""

import pytest

from tokensaver.providers import (
    OpenAIAdapter,
    AnthropicAdapter,
    OllamaAdapter,
    NormalizedRequest,
    NormalizedMessage,
    MODEL_REGISTRY,
    Provider,
    get_cheapest_provider,
    get_adapter,
)


def test_openai_adapter_to_api():
    adapter = OpenAIAdapter()
    request = NormalizedRequest(
        model="gpt-4o",
        messages=[
            NormalizedMessage(role="system", content="You are helpful."),
            NormalizedMessage(role="user", content="Hello!"),
        ],
    )
    result = adapter.to_api_format(request)
    assert result["model"] == "gpt-4o"
    assert len(result["messages"]) == 2
    assert result["messages"][0]["role"] == "system"
    assert result["stream"] is False


def test_openai_adapter_from_response():
    adapter = OpenAIAdapter()
    response = {
        "model": "gpt-4o",
        "choices": [{"message": {"content": "Hi there!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    result = adapter.from_api_response(response, "gpt-4o")
    assert result.content == "Hi there!"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.provider == Provider.OPENAI


def test_anthropic_adapter_to_api():
    adapter = AnthropicAdapter()
    request = NormalizedRequest(
        model="claude-3.5-sonnet",
        messages=[
            NormalizedMessage(role="system", content="You are helpful."),
            NormalizedMessage(role="user", content="Hello!"),
        ],
    )
    result = adapter.to_api_format(request)
    assert result["model"] == "claude-3.5-sonnet"
    assert result["system"] == "You are helpful."
    assert len(result["messages"]) == 1  # system is separated


def test_anthropic_adapter_from_response():
    adapter = AnthropicAdapter()
    response = {
        "model": "claude-3.5-sonnet",
        "content": [{"type": "text", "text": "Hello!"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = adapter.from_api_response(response, "claude-3.5-sonnet")
    assert result.content == "Hello!"
    assert result.input_tokens == 10
    assert result.provider == Provider.ANTHROPIC


def test_ollama_adapter_to_api():
    adapter = OllamaAdapter()
    request = NormalizedRequest(
        model="llama3.1",
        messages=[NormalizedMessage(role="user", content="Hello!")],
    )
    result = adapter.to_api_format(request)
    assert result["model"] == "llama3.1"
    assert "options" in result


def test_ollama_adapter_cost_is_zero():
    adapter = OllamaAdapter()
    cost = adapter.get_cost_estimate(1000, 500)
    assert cost == 0.0


def test_model_registry_has_models():
    assert "gpt-4o" in MODEL_REGISTRY
    assert "gpt-4o-mini" in MODEL_REGISTRY
    assert "claude-3.5-sonnet" in MODEL_REGISTRY
    assert "llama3.1" in MODEL_REGISTRY


def test_model_registry_costs():
    gpt4o = MODEL_REGISTRY["gpt-4o"]
    gpt4o_mini = MODEL_REGISTRY["gpt-4o-mini"]
    assert gpt4o.cost_per_1k_input > gpt4o_mini.cost_per_1k_input


def test_get_cheapest_provider_local():
    provider, model, cost = get_cheapest_provider(100, exclude=[Provider.OLLAMA])
    assert provider != Provider.OLLAMA
    assert cost >= 0


def test_get_cheapest_provider_with_ollama():
    provider, model, cost = get_cheapest_provider(100)
    # Ollama should be cheapest (free)
    assert cost == 0.0


def test_get_adapter():
    adapter = get_adapter(Provider.OPENAI)
    assert isinstance(adapter, OpenAIAdapter)

    adapter = get_adapter(Provider.ANTHROPIC)
    assert isinstance(adapter, AnthropicAdapter)

    adapter = get_adapter(Provider.OLLAMA)
    assert isinstance(adapter, OllamaAdapter)
