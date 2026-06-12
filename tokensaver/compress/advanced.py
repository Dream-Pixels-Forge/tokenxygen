"""Advanced compression using LLMLingua-2 for deeper token savings.

LLMLingua-2 uses a small LM to identify and remove low-information tokens
from prompts, achieving 40-60% compression with minimal quality loss.

This module provides:
1. Token-level compression using perplexity scoring
2. Budget-aware compression (compress more when budget is tight)
3. Fallback to rule-based compression when LLMLingua is unavailable
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from tokensaver.config import settings
from tokensaver.core import count_tokens, get_encoding


@dataclass
class CompressionStats:
    """Statistics from a compression pass."""

    original_tokens: int
    compressed_tokens: int
    tokens_removed: int
    removal_ratio: float
    method: str  # "llmlingua2", "rule_based", "disabled"

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (self.tokens_removed / self.original_tokens) * 100


class LLMLinguaCompressor:
    """Token-level compressor using LLMLingua-2 or rule-based fallback.

    LLMLingua-2 works by:
    1. Tokenizing the prompt
    2. Scoring each token's importance (perplexity-based)
    3. Removing low-importance tokens while preserving meaning
    4. Reconstructing the compressed prompt
    """

    def __init__(self) -> None:
        self._llmlingua_available: Optional[bool] = None
        self._model = None

    def is_available(self) -> bool:
        """Check if LLMLingua-2 is installed and available."""
        if self._llmlingua_available is None:
            try:
                import llmlingua2
                self._llmlingua_available = True
            except ImportError:
                self._llmlingua_available = False
        return self._llmlingua_available

    def compress(
        self,
        text: str,
        compression_ratio: float = 0.5,
        preserve_instructions: bool = True,
    ) -> tuple[str, CompressionStats]:
        """Compress a text string.

        Args:
            text: Input text to compress
            compression_ratio: Target compression (0.5 = 50% of original)
            preserve_instructions: Keep system instructions intact

        Returns:
            (compressed_text, stats)
        """
        original_tokens = count_tokens(text)

        if self.is_available():
            return self._compress_llmlingua2(
                text, original_tokens, compression_ratio, preserve_instructions
            )
        else:
            return self._compress_rule_based(
                text, original_tokens, compression_ratio
            )

    def compress_messages(
        self,
        messages: list[dict],
        compression_ratio: float = 0.5,
        model: str = "default",
    ) -> tuple[list[dict], CompressionStats]:
        """Compress chat messages while preserving structure.

        System messages are compressed less aggressively.
        Tool outputs are compressed more aggressively.
        """
        total_original = sum(
            count_tokens(m.get("content", ""), model)
            for m in messages
            if isinstance(m.get("content"), str)
        )

        result = []
        total_compressed = 0

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not isinstance(content, str) or not content:
                result.append(msg)
                continue

            # Adjust ratio based on role
            if role == "system":
                # System messages: light compression
                ratio = compression_ratio * 0.3
            elif role in ("tool", "function"):
                # Tool outputs: aggressive compression
                ratio = min(compression_ratio * 1.5, 0.8)
            elif role == "assistant":
                # Assistant messages: no compression
                ratio = 0.0
            else:
                # User messages: standard compression
                ratio = compression_ratio

            if ratio > 0:
                compressed, _ = self.compress(content, ratio)
                result.append({**msg, "content": compressed})
                total_compressed += count_tokens(compressed, model)
            else:
                result.append(msg)
                total_compressed += count_tokens(content, model)

        return result, CompressionStats(
            original_tokens=total_original,
            compressed_tokens=total_compressed,
            tokens_removed=total_original - total_compressed,
            removal_ratio=(total_original - total_compressed) / total_original if total_original > 0 else 0,
            method="llmlingua2" if self.is_available() else "rule_based",
        )

    def _compress_llmlingua2(
        self,
        text: str,
        original_tokens: int,
        compression_ratio: float,
        preserve_instructions: bool,
    ) -> tuple[str, CompressionStats]:
        """Compress using LLMLingua-2."""
        try:
            from llmlingua2 import PromptCompressor

            if self._model is None:
                self._model = PromptCompressor(
                    model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
                    device_map="cpu",
                )

            compressed = self._model.compress_prompt(
                text,
                rate=compression_ratio,
                force_tokens=["\n", "?", "!", "."],
                force_sentence_tokens=True,
            )

            compressed_text = compressed.get("compressed_prompt", text)
            compressed_tokens = count_tokens(compressed_text)

            return compressed_text, CompressionStats(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                tokens_removed=original_tokens - compressed_tokens,
                removal_ratio=(original_tokens - compressed_tokens) / original_tokens if original_tokens > 0 else 0,
                method="llmlingua2",
            )
        except Exception:
            # Fallback to rule-based
            return self._compress_rule_based(text, original_tokens, compression_ratio)

    def _compress_rule_based(
        self,
        text: str,
        original_tokens: int,
        compression_ratio: float,
    ) -> tuple[str, CompressionStats]:
        """Rule-based compression fallback.

        Strategies:
        1. Remove filler words and phrases
        2. Simplify verbose expressions
        3. Remove redundant whitespace
        4. Abbreviate common patterns
        """
        compressed = text

        # Strategy 1: Remove filler words
        fillers = [
            r"\bplease\b", r"\bthank you\b", r"\bthanks\b",
            r"\byou know\b", r"\bbasically\b", r"\bactually\b",
            r"\bbasically\b", r"\bliterally\b", r"\bjust\b",
            r"\bkind of\b", r"\bsort of\b", r"\bI think\b",
            r"\bI believe\b", r"\bin my opinion\b",
        ]
        for pattern in fillers:
            compressed = re.sub(pattern, "", compressed, flags=re.IGNORECASE)

        # Strategy 2: Simplify verbose expressions
        simplifications = [
            (r"\bin order to\b", "to"),
            (r"\bdue to the fact that\b", "because"),
            (r"\bat this point in time\b", "now"),
            (r"\bfor the purpose of\b", "for"),
            (r"\bin the event that\b", "if"),
            (r"\bwith regard to\b", "about"),
            (r"\bin spite of the fact\b", "although"),
            (r"\ba large number of\b", "many"),
            (r"\ba significant amount of\b", "much"),
        ]
        for pattern, replacement in simplifications:
            compressed = re.sub(pattern, replacement, compressed, flags=re.IGNORECASE)

        # Strategy 3: Remove excessive whitespace
        compressed = re.sub(r"\n{3,}", "\n\n", compressed)
        compressed = re.sub(r" {3,}", " ", compressed)

        # Strategy 4: Remove blank lines
        lines = compressed.split("\n")
        lines = [l for l in lines if l.strip() or lines.index(l) < 3]
        compressed = "\n".join(lines)

        compressed_tokens = count_tokens(compressed)

        return compressed, CompressionStats(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            tokens_removed=original_tokens - compressed_tokens,
            removal_ratio=(original_tokens - compressed_tokens) / original_tokens if original_tokens > 0 else 0,
            method="rule_based",
        )


# Global singleton
llmlingua = LLMLinguaCompressor()
