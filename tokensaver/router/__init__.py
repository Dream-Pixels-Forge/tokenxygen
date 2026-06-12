"""Smart model router — classify prompts and route to cheapest capable model.

Routing tiers:
  Tier 1 (simple):  greetings, yes/no, simple questions → gpt-4o-mini
  Tier 2 (medium):  code explanations, summaries, moderate tasks → gpt-4o-mini
  Tier 3 (complex): complex reasoning, long code, architecture → gpt-4o
  Tier 4 (expert):  multi-step plans, critical code, security → gpt-4o
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from tokensaver.config import settings


class PromptTier(Enum):
    SIMPLE = 1
    MEDIUM = 2
    COMPLEX = 3
    EXPERT = 4


@dataclass
class RoutingDecision:
    original_model: str
    routed_model: str
    tier: PromptTier
    reason: str


# Signals that indicate complexity
COMPLEXITY_SIGNALS = {
    "high": [
        # Multi-file / architecture keywords
        r"\b(architecture|refactor|design pattern|system design|scalab)\b",
        # Security / critical
        r"\b(security|vulnerability|audit|penetration|encrypt|auth)\b",
        # Complex reasoning
        r"\b(prove|derive|explain.*why|analyze.*trade.?off|compare.*approach)\b",
        # Long code indicators
        r"\b(implementation|full.?stack|end.?to.?end|migration|deploy)\b",
        # Multi-step
        r"\b(step\s*by\s*step|plan|roadmap|strategy|breakdown)\b",
    ],
    "medium": [
        # Code-related
        r"\b(code|function|class|method|bug|fix|error|debug|test)\b",
        # Explanations
        r"\b(explain|how does|what is|describe|summarize|review)\b",
        # Refactoring
        r"\b(optimize|improve|clean|rewrite|update)\b",
    ],
    "low": [
        # Greetings / simple
        r"^(hi|hello|hey|thanks|thank you|ok|yes|no|sure|great)\s*[!.?]*$",
        # Simple questions
        r"\b(what time|how many|count|list|name)\b",
    ],
}


class PromptRouter:
    """Classify prompts and route to appropriate models."""

    def __init__(self) -> None:
        self.enabled = settings.router.enabled
        self.cheap_model = settings.router.cheap_model
        self.expensive_model = settings.router.expensive_model
        # Model tiers: cheap handles tier 1-2, expensive handles 3-4
        self.model_tiers = {
            self.cheap_model: [PromptTier.SIMPLE, PromptTier.MEDIUM],
            self.expensive_model: [PromptTier.COMPLEX, PromptTier.EXPERT],
        }

    def route(
        self,
        messages: list[dict],
        requested_model: str,
        token_count: int,
    ) -> RoutingDecision:
        """Decide which model to use based on prompt content.

        Returns RoutingDecision with the chosen model and reasoning.
        """
        if not self.enabled:
            return RoutingDecision(
                original_model=requested_model,
                routed_model=requested_model,
                tier=PromptTier.MEDIUM,
                reason="routing_disabled",
            )

        # If user explicitly requests a specific model (not in our tier list),
        # respect their choice
        if requested_model not in (self.cheap_model, self.expensive_model):
            return RoutingDecision(
                original_model=requested_model,
                routed_model=requested_model,
                tier=PromptTier.MEDIUM,
                reason="custom_model_preserved",
            )

        tier = self._classify(messages, token_count)
        routed = self._pick_model(tier)
        reason = f"tier_{tier.name.lower()}"

        if routed != requested_model:
            reason += f"_downgraded"

        return RoutingDecision(
            original_model=requested_model,
            routed_model=routed,
            tier=tier,
            reason=reason,
        )

    def _classify(self, messages: list[dict], token_count: int) -> PromptTier:
        """Classify a prompt into a complexity tier."""
        # Combine all user/system messages for analysis
        text = self._extract_text(messages).lower()

        # Score-based classification
        score = 0

        # Token-based heuristics
        if token_count > 4000:
            score += 3  # Long context = complex
        elif token_count > 1500:
            score += 2
        elif token_count > 500:
            score += 1

        # Pattern matching
        for pattern in COMPLEXITY_SIGNALS["high"]:
            if re.search(pattern, text, re.IGNORECASE):
                score += 2

        for pattern in COMPLEXITY_SIGNALS["medium"]:
            if re.search(pattern, text, re.IGNORECASE):
                score += 1

        for pattern in COMPLEXITY_SIGNALS["low"]:
            if re.search(pattern, text, re.IGNORECASE):
                score -= 1

        # Code blocks increase complexity
        code_block_count = text.count("```")
        if code_block_count >= 4:
            score += 2  # Multiple file references
        elif code_block_count >= 2:
            score += 1

        # Multiple file references
        file_ref_count = len(re.findall(r"(?:file|path|src)/", text))
        if file_ref_count >= 3:
            score += 2

        # Map score to tier
        if score <= 0:
            return PromptTier.SIMPLE
        elif score <= 2:
            return PromptTier.MEDIUM
        elif score <= 4:
            return PromptTier.COMPLEX
        else:
            return PromptTier.EXPERT

    def _pick_model(self, tier: PromptTier) -> str:
        for model, tiers in self.model_tiers.items():
            if tier in tiers:
                return model
        return self.expensive_model

    def _extract_text(self, messages: list[dict]) -> str:
        parts = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                # Handle multipart content
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
        return "\n".join(parts)


# Global singleton
router = PromptRouter()
