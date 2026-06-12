"""Plugin system for custom compression strategies.

Users can register custom strategies that run alongside built-in ones.
Each strategy receives messages and returns (modified_messages, savings_info).
"""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("tokenxygen.plugins")


class MessageDict(dict[str, Any]):
    """Typed dict for chat messages."""
    pass


@dataclass
class StrategyResult:
    """Result from a compression strategy."""

    saved_tokens: int
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class CompressionStrategy(ABC):
    """Base class for custom compression strategies."""

    name: str = "unnamed"
    description: str = ""
    priority: int = 50  # Lower = runs first
    min_tokens: int = 0  # Skip if fewer tokens

    @abstractmethod
    def apply(
        self, messages: list[dict[str, Any]], token_count_fn: Callable[[str], int]
    ) -> tuple[list[dict[str, Any]], StrategyResult]:
        """Apply the strategy to messages.

        Args:
            messages: List of chat messages
            token_count_fn: Function to count tokens in a string

        Returns:
            (modified_messages, result)
        """
        ...

    def should_run(self, messages: list[dict[str, Any]], token_count: int) -> bool:
        """Override to conditionally skip this strategy."""
        return token_count >= self.min_tokens


class PluginRegistry:
    """Registry for compression strategies."""

    def __init__(self) -> None:
        self._strategies: list[CompressionStrategy] = []
        self._loaded = False

    def register(self, strategy: CompressionStrategy) -> None:
        """Register a compression strategy."""
        self._strategies.append(strategy)
        self._strategies.sort(key=lambda s: s.priority)
        logger.info("Registered strategy: %s (priority=%d)", strategy.name, strategy.priority)

    def unregister(self, name: str) -> bool:
        """Unregister a strategy by name."""
        before = len(self._strategies)
        self._strategies = [s for s in self._strategies if s.name != name]
        return len(self._strategies) < before

    def get_all(self) -> list[CompressionStrategy]:
        """Get all registered strategies in priority order."""
        return list(self._strategies)

    def get_enabled(self, messages: list[dict], token_count: int) -> list[CompressionStrategy]:
        """Get strategies that should run for the given input."""
        return [s for s in self._strategies if s.should_run(messages, token_count)]

    def load_plugins_from_directory(self, directory: str | Path) -> int:
        """Load plugin .py files from a directory.

        Each file should define a STRATEGY variable that is a CompressionStrategy instance.
        """
        directory = Path(directory)
        if not directory.exists():
            return 0

        loaded = 0
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"tokenxygen.plugins.{py_file.stem}", py_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    if hasattr(module, "STRATEGY"):
                        strategy = module.STRATEGY
                        if isinstance(strategy, CompressionStrategy):
                            self.register(strategy)
                            loaded += 1
                            logger.info("Loaded plugin: %s from %s", strategy.name, py_file)
            except Exception as e:
                logger.warning("Failed to load plugin %s: %s", py_file, e)

        return loaded

    def load_builtin_plugins(self) -> int:
        """Load built-in plugins from the plugins directory."""
        plugins_dir = Path(__file__).parent / "builtin"
        return self.load_plugins_from_directory(plugins_dir)


# Global registry
registry = PluginRegistry()


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------

class DeduplicateToolOutputs(CompressionStrategy):
    """Remove duplicate tool/function call outputs."""

    name = "dedup_tool_outputs"
    description = "Remove repeated tool outputs from context"
    priority = 10

    def apply(self, messages, token_count_fn):
        seen_outputs: dict[str, int] = {}
        result_msgs = []
        removed = 0

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Only dedup tool/function outputs
            if role in ("tool", "function") and isinstance(content, str) and len(content) > 100:
                h = hash(content[:200])
                if h in seen_outputs:
                    removed += 1
                    result_msgs.append({
                        **msg,
                        "content": f"[Duplicate output, {len(content)} chars omitted]",
                    })
                    continue
                seen_outputs[h] = len(result_msgs)

            result_msgs.append(msg)

        saved = sum(token_count_fn(m.get("content", "")) for m in messages if m.get("content")) - \
                sum(token_count_fn(m.get("content", "")) for m in result_msgs if m.get("content"))

        return result_msgs, StrategyResult(
            saved_tokens=max(0, saved),
            details=f"Removed {removed} duplicate tool outputs",
        )


class CompressFileDiffs(CompressionStrategy):
    """Compress large file diffs by keeping only changed sections."""

    name = "compress_diffs"
    description = "Compress large unified diffs"
    priority = 20

    def apply(self, messages, token_count_fn):
        result_msgs = []
        compressed = 0

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                result_msgs.append(msg)
                continue

            # Detect unified diff
            if self._is_diff(content) and len(content) > 500:
                compressed_content = self._compress_diff(content)
                if len(compressed_content) < len(content):
                    result_msgs.append({**msg, "content": compressed_content})
                    compressed += 1
                    continue

            result_msgs.append(msg)

        original_tokens = sum(token_count_fn(m.get("content", "")) for m in messages)
        new_tokens = sum(token_count_fn(m.get("content", "")) for m in result_msgs)

        return result_msgs, StrategyResult(
            saved_tokens=max(0, original_tokens - new_tokens),
            details=f"Compressed {compressed} file diffs",
        )

    def _is_diff(self, text: str) -> bool:
        diff_lines = [line for line in text.split("\n") if line.startswith("+") or line.startswith("-")]
        return len(diff_lines) > 10

    def _compress_diff(self, diff: str) -> str:
        lines = diff.split("\n")
        result = []
        context_count = 0
        max_context = 3

        for line in lines:
            if line.startswith("+") or line.startswith("-"):
                result.append(line)
                context_count = 0
            elif line.startswith("@@"):
                result.append(line)
                context_count = 0
            elif line.startswith("diff ") or line.startswith("---") or line.startswith("+++"):
                result.append(line)
            else:
                context_count += 1
                if context_count <= max_context:
                    result.append(line)
                elif context_count == max_context + 1:
                    result.append("... (context omitted) ...")

        return "\n".join(result)


class SummarizeLongImports(CompressionStrategy):
    """Replace long import blocks with a summary."""

    name = "summarize_imports"
    description = "Summarize long import blocks"
    priority = 30

    IMPORT_PATTERNS = (
        "import ", "from ", "require(", "#include", "use ", "using ",
    )

    def apply(self, messages, token_count_fn):
        result_msgs = []
        compressed = 0

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                result_msgs.append(msg)
                continue

            lines = content.split("\n")
            import_lines = []
            other_lines = []
            in_imports = True

            for line in lines:
                stripped = line.strip()
                if any(stripped.startswith(p) for p in self.IMPORT_PATTERNS):
                    import_lines.append(stripped)
                elif stripped == "" and in_imports:
                    continue  # skip blank lines between imports
                else:
                    in_imports = False
                    other_lines.append(line)

            if len(import_lines) > 5:
                summary = f"[{len(import_lines)} imports summarized]"
                result_msgs.append({**msg, "content": "\n".join([summary] + other_lines)})
                compressed += 1
            else:
                result_msgs.append(msg)

        original_tokens = sum(token_count_fn(m.get("content", "")) for m in messages)
        new_tokens = sum(token_count_fn(m.get("content", "")) for m in result_msgs)

        return result_msgs, StrategyResult(
            saved_tokens=max(0, original_tokens - new_tokens),
            details=f"Summarized {compressed} import blocks",
        )


# Register built-in strategies
registry.register(DeduplicateToolOutputs())
registry.register(CompressFileDiffs())
registry.register(SummarizeLongImports())
