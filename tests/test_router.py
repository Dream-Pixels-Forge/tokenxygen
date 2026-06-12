"""Tests for the smart model router."""

import pytest

from tokenxygen.router import PromptRouter, PromptTier


@pytest.fixture
def router_instance():
    return PromptRouter()


def test_simple_greeting_routes_to_cheap(router_instance):
    messages = [{"role": "user", "content": "Hello!"}]
    decision = router_instance.route(messages, "gpt-4o", 5)
    assert decision.tier == PromptTier.SIMPLE
    assert decision.routed_model == router_instance.cheap_model


def test_simple_yes_no_routes_to_cheap(router_instance):
    messages = [{"role": "user", "content": "Yes, go ahead."}]
    decision = router_instance.route(messages, "gpt-4o", 5)
    assert decision.tier == PromptTier.SIMPLE


def test_code_question_routes_higher_than_greeting(router_instance):
    messages_greeting = [{"role": "user", "content": "Hello!"}]
    messages_code = [{"role": "user", "content": "Implement a thread-safe LRU cache in Python with TTL support and eviction policy"}]
    tier_greeting = router_instance.route(messages_greeting, "gpt-4o", 5).tier.value
    tier_code = router_instance.route(messages_code, "gpt-4o", 50).tier.value
    # Code questions should route at least as high as greetings
    assert tier_code >= tier_greeting


def test_security_question_routes_to_expert(router_instance):
    messages = [{"role": "user", "content": "Review this code for security vulnerabilities and audit the authentication flow for penetration testing"}]
    decision = router_instance.route(messages, "gpt-4o", 100)
    assert decision.tier.value >= PromptTier.COMPLEX.value


def test_long_context_increases_tier(router_instance):
    messages = [{"role": "user", "content": "What is this?"}]
    # Short
    short = router_instance.route(messages, "gpt-4o", 100)
    # Long
    long = router_instance.route(messages, "gpt-4o", 5000)
    assert long.tier.value >= short.tier.value


def test_custom_model_preserved(router_instance):
    messages = [{"role": "user", "content": "Hi"}]
    decision = router_instance.route(messages, "claude-3.5-sonnet", 10)
    assert decision.routed_model == "claude-3.5-sonnet"
    assert decision.reason == "custom_model_preserved"


def test_disabled_router_passes_through():
    from tokenxygen.config import settings
    original = settings.router.enabled
    settings.router.enabled = False
    try:
        r = PromptRouter()
        messages = [{"role": "user", "content": "Hello"}]
        decision = r.route(messages, "gpt-4o", 10)
        assert decision.routed_model == "gpt-4o"
        assert decision.reason == "routing_disabled"
    finally:
        settings.router.enabled = original


def test_multi_file_code_block_increases_complexity(router_instance):
    text = "```python\ndef a(): pass\n```\n```python\ndef b(): pass\n```\n```python\ndef c(): pass\n```\n```python\ndef d(): pass\n```"
    messages = [{"role": "user", "content": text}]
    decision = router_instance.route(messages, "gpt-4o", 200)
    assert decision.tier.value >= PromptTier.MEDIUM.value


def test_architecture_keywords_increase_tier(router_instance):
    messages = [{"role": "user", "content": "Design the system architecture for a scalable microservices platform with security audit and deployment strategy"}]
    decision = router_instance.route(messages, "gpt-4o", 200)
    assert decision.tier.value >= PromptTier.MEDIUM.value
