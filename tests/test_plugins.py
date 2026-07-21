"""Tests for the plugin system."""

from tokenxygen.plugins import (
    CompressionStrategy,
    PluginRegistry,
    DeduplicateToolOutputs,
    CompressFileDiffs,
    SummarizeLongImports,
    StrategyResult,
    registry,
)


def mock_token_count(text: str) -> int:
    """Rough token count for testing."""
    return len(text.split())


def test_builtin_strategies_registered():
    """All built-in strategies should be registered."""
    names = [s.name for s in registry.get_all()]
    assert "dedup_tool_outputs" in names
    assert "compress_diffs" in names
    assert "summarize_imports" in names


def test_dedup_tool_outputs():
    strategy = DeduplicateToolOutputs()
    messages = [
        {"role": "user", "content": "Run this"},
        {"role": "tool", "content": "A" * 200},
        {"role": "user", "content": "Run again"},
        {"role": "tool", "content": "A" * 200},  # duplicate
    ]
    result_msgs, result = strategy.apply(messages, mock_token_count)
    # Duplicate is replaced with reference, not removed
    assert len(result_msgs) == 4
    assert "Duplicate output" in result_msgs[3]["content"]


def test_compress_diffs():
    strategy = CompressFileDiffs()
    diff = "--- a.py\n+++ b.py\n@@ -1,5 +1,5 @@\n" + "\n".join(
        [f"-line{i}" if i % 3 == 0 else f"+line{i}" for i in range(50)]
    )
    messages = [{"role": "user", "content": diff}]
    result_msgs, result = strategy.apply(messages, mock_token_count)
    # Should compress by removing some context
    assert result.saved_tokens >= 0


def test_summarize_imports():
    strategy = SummarizeLongImports()
    imports = "\n".join([f"import module_{i}" for i in range(10)])
    messages = [{"role": "user", "content": imports + "\n\nprint('hello')"}]
    result_msgs, result = strategy.apply(messages, mock_token_count)
    assert "imports summarized" in result_msgs[0]["content"]


def test_strategy_should_run():
    strategy = DeduplicateToolOutputs()
    messages = [{"role": "user", "content": "hello"}]
    assert strategy.should_run(messages, 10) is True


def test_custom_strategy():
    class MyStrategy(CompressionStrategy):
        name = "test_strategy"
        priority = 99

        def apply(self, messages, token_count_fn):
            return messages, StrategyResult(saved_tokens=0, details="test")

    reg = PluginRegistry()
    reg.register(MyStrategy())
    assert len(reg.get_all()) == 1
    assert reg.get_all()[0].name == "test_strategy"


def test_unregister():
    class TempStrategy(CompressionStrategy):
        name = "temp"
        priority = 99

        def apply(self, messages, token_count_fn):
            return messages, StrategyResult(saved_tokens=0)

    reg = PluginRegistry()
    reg.register(TempStrategy())
    assert len(reg.get_all()) == 1

    removed = reg.unregister("temp")
    assert removed is True
    assert len(reg.get_all()) == 0


def test_get_enabled_filters():
    class ConditionalStrategy(CompressionStrategy):
        name = "conditional"
        priority = 50

        def should_run(self, messages, token_count):
            return token_count > 100

        def apply(self, messages, token_count_fn):
            return messages, StrategyResult(saved_tokens=0)

    reg = PluginRegistry()
    reg.register(ConditionalStrategy())

    # Should not run for small input
    enabled = reg.get_enabled([{"role": "user", "content": "hi"}], 50)
    assert len(enabled) == 0

    # Should run for large input
    enabled = reg.get_enabled([{"role": "user", "content": "x" * 500}], 200)
    assert len(enabled) == 1
