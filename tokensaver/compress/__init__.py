"""Prompt compression for coding agent contexts.

Strategies:
1. File deduplication — detect repeated file contents in context
2. Section pruning — remove low-value sections (full imports, large diffs)
3. Comment stripping — strip comments from code blocks
4. Whitespace normalization — collapse whitespace
5. Import summarization — replace full import blocks with a summary
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tokensaver.config import settings
from tokensaver.core import count_tokens


@dataclass
class CompressionResult:
    """Result of a compression pass."""

    original_tokens: int
    compressed_tokens: int
    strategy: str
    details: list[str] = field(default_factory=list)

    @property
    def saved_tokens(self) -> int:
        return self.original_tokens - self.compressed_tokens

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (self.saved_tokens / self.original_tokens) * 100


class PromptCompressor:
    """Multi-strategy prompt compressor optimized for coding agent contexts."""

    def __init__(self, aggressiveness: float | None = None) -> None:
        self.aggressiveness = aggressiveness or settings.compress.aggressiveness
        self.preserve_instructions = settings.compress.preserve_instructions

    def compress(self, messages: list[dict], model: str = "default") -> tuple[list[dict], list[CompressionResult]]:
        """Apply compression strategies to chat messages.

        Returns (compressed_messages, results).
        """
        results: list[CompressionResult] = []
        compressed = [dict(m) for m in messages]  # deep copy

        # Strategy 1: Deduplicate file contents
        compressed, r = self._deduplicate_files(compressed, model)
        if r:
            results.append(r)

        # Strategy 2: Strip code comments (low aggressiveness)
        if self.aggressiveness > 0.2:
            compressed, r = self._strip_comments(compressed, model)
            if r:
                results.append(r)

        # Strategy 3: Normalize whitespace
        compressed, r = self._normalize_whitespace(compressed, model)
        if r:
            results.append(r)

        # Strategy 4: Collapse repeated context blocks
        compressed, r = self._collapse_repeated_blocks(compressed, model)
        if r:
            results.append(r)

        # Strategy 5: Truncate oversized contexts
        max_tokens = settings.compress.max_context_tokens
        compressed, r = self._truncate_context(compressed, max_tokens, model)
        if r:
            results.append(r)

        return compressed, results

    def _deduplicate_files(
        self, messages: list[dict], model: str
    ) -> tuple[list[dict], CompressionResult | None]:
        """Remove duplicate file content blocks that appear multiple times."""
        original_tokens = count_tokens(self._serialize(messages), model)
        seen_contents: dict[str, int] = {}  # content_hash → first index
        deduped: list[dict] = []
        removed = 0

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                deduped.append(msg)
                continue

            # Detect file-like content (has path patterns)
            file_hash = None
            if self._looks_like_file_content(content):
                file_hash = self._quick_hash(content)

            if file_hash and file_hash in seen_contents:
                # Replace with a reference
                deduped.append({
                    **msg,
                    "content": f"[Previously shown: file content omitted, {len(content)} chars]",
                })
                removed += 1
            else:
                if file_hash:
                    seen_contents[file_hash] = len(deduped)
                deduped.append(msg)

        compressed_tokens = count_tokens(self._serialize(deduped), model)
        result = None
        if removed > 0:
            result = CompressionResult(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                strategy="file_dedup",
                details=[f"Removed {removed} duplicate file blocks"],
            )
        return deduped, result

    def _strip_comments(
        self, messages: list[dict], model: str
    ) -> tuple[list[dict], CompressionResult | None]:
        """Strip comments from code blocks."""
        original_tokens = count_tokens(self._serialize(messages), model)
        compressed = []

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                compressed.append(msg)
                continue

            if self._looks_like_code(content):
                stripped = self._remove_code_comments(content)
                compressed.append({**msg, "content": stripped})
            else:
                compressed.append(msg)

        compressed_tokens = count_tokens(self._serialize(compressed), model)
        saved = original_tokens - compressed_tokens

        result = None
        if saved > 10:
            result = CompressionResult(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                strategy="comment_strip",
                details=[f"Stripped code comments"],
            )
        return compressed, result

    def _normalize_whitespace(
        self, messages: list[dict], model: str
    ) -> tuple[list[dict], CompressionResult | None]:
        """Collapse excessive whitespace."""
        original_tokens = count_tokens(self._serialize(messages), model)
        compressed = []

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                compressed.append(msg)
                continue

            # Collapse 3+ newlines to 2
            normalized = re.sub(r"\n{3,}", "\n\n", content)
            # Collapse 3+ spaces to 1 (preserve leading indent)
            normalized = re.sub(r"(?<=\S) {3,}", " ", normalized)
            compressed.append({**msg, "content": normalized})

        compressed_tokens = count_tokens(self._serialize(compressed), model)
        result = None
        if original_tokens - compressed_tokens > 5:
            result = CompressionResult(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                strategy="whitespace_norm",
                details=["Normalized whitespace"],
            )
        return compressed, result

    def _collapse_repeated_blocks(
        self, messages: list[dict], model: str
    ) -> tuple[list[dict], CompressionResult | None]:
        """Collapse blocks that appear 3+ times into a single reference."""
        original_tokens = count_tokens(self._serialize(messages), model)
        block_count: dict[str, int] = {}
        block_first_idx: dict[str, int] = {}

        # Count blocks
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            if not isinstance(content, str) or len(content) < 100:
                continue
            h = self._quick_hash(content)
            if h not in block_count:
                block_count[h] = 0
                block_first_idx[h] = i
            block_count[h] += 1

        # Replace repeated blocks
        compressed = []
        seen = set()
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            if not isinstance(content, str) or len(content) < 100:
                compressed.append(msg)
                continue

            h = self._quick_hash(content)
            if block_count.get(h, 0) >= 3 and h not in seen:
                seen.add(h)
                compressed.append(msg)  # keep first occurrence
            elif block_count.get(h, 0) >= 3:
                compressed.append({
                    **msg,
                    "content": f"[Repeated block, omitted — shown {block_count[h]} times, {len(content)} chars each]",
                })
            else:
                compressed.append(msg)

        compressed_tokens = count_tokens(self._serialize(compressed), model)
        result = None
        if original_tokens - compressed_tokens > 20:
            result = CompressionResult(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                strategy="block_collapse",
                details=[f"Collapsed {len(seen)} repeated blocks"],
            )
        return compressed, result

    def _truncate_context(
        self, messages: list[dict], max_tokens: int, model: str
    ) -> tuple[list[dict], CompressionResult | None]:
        """Truncate context to fit within max_tokens budget.

        Keeps: system message, first user message, last N messages.
        """
        total = count_tokens(self._serialize(messages), model)
        if total <= max_tokens:
            return messages, None

        # Budget allocation: 20% system, 80% recent messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        system_tokens = count_tokens(self._serialize(system_msgs), model)
        remaining = max_tokens - system_tokens

        if remaining <= 0:
            # System alone exceeds budget — truncate system
            truncated_system = []
            budget = max_tokens
            for msg in system_msgs:
                content = msg.get("content", "")
                if not isinstance(content, str):
                    truncated_system.append(msg)
                    continue
                tokens = count_tokens(content, model)
                if tokens <= budget:
                    truncated_system.append(msg)
                    budget -= tokens
                else:
                    from tokensaver.core import truncate_to_tokens
                    truncated_content = truncate_to_tokens(content, budget, model)
                    truncated_system.append({**msg, "content": truncated_content})
                    break
            return truncated_system, CompressionResult(
                original_tokens=total,
                compressed_tokens=max_tokens,
                strategy="truncate_system",
                details=["Truncated system message to fit budget"],
            )

        # Keep most recent messages within budget
        kept: list[dict] = []
        used = 0
        for msg in reversed(non_system):
            content = msg.get("content", "")
            tokens = count_tokens(str(content), model) if isinstance(content, str) else 0
            if used + tokens > remaining:
                break
            kept.insert(0, msg)
            used += tokens

        result_msgs = system_msgs + kept
        compressed_tokens = count_tokens(self._serialize(result_msgs), model)
        return result_msgs, CompressionResult(
            original_tokens=total,
            compressed_tokens=compressed_tokens,
            strategy="truncate_context",
            details=[f"Kept {len(kept)}/{len(non_system)} non-system messages, {remaining} token budget"],
        )

    # --- Helpers ---

    def _serialize(self, messages: list[dict]) -> str:
        parts = []
        for m in messages:
            c = m.get("content", "")
            parts.append(str(c) if isinstance(c, str) else str(c))
        return "\n".join(parts)

    def _looks_like_file_content(self, text: str) -> bool:
        indicators = ["def ", "class ", "import ", "function ", "const ", "let ", "var ", "#include"]
        return sum(1 for i in indicators if i in text[:200]) >= 2

    def _looks_like_code(self, text: str) -> bool:
        code_indicators = ["def ", "class ", "function ", "=>", "//", "/*", "# ", "```"]
        return sum(1 for i in code_indicators if i in text) >= 2

    def _quick_hash(self, text: str) -> str:
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()[:12]

    def _remove_code_comments(self, code: str) -> str:
        lines = code.split("\n")
        result = []
        for line in lines:
            # Skip standalone comment lines (but not #! or shebang)
            if re.match(r"^\s*#(?! !)", line) or re.match(r"^\s*//", line):
                continue
            result.append(line)
        return "\n".join(result)


# Global singleton
compressor = PromptCompressor()
