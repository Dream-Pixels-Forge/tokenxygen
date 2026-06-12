# 🚀 TokenSaver

**Universal token optimizer for coding agents — save 40-70% on LLM costs.**

TokenSaver is a drop-in proxy that sits between your coding agent (Claude Code, Cursor, Windsurf, Codex) and LLM APIs, automatically optimizing tokens in-flight. Zero code changes required.

```
┌─────────────┐     ┌────────────────┐     ┌──────────┐
│  Coding      │────▶│  TokenSaver    │────▶│  OpenAI  │
│  Agent       │◀────│  Proxy         │◀────│  API     │
└─────────────┘     └────────────────┘     └──────────┘
                    🎯 Cache | Compress | Route | Budget
```

## ⚡ Quick Start

```bash
pip install tokensaver

# Start the proxy
tokensaver serve

# In another terminal — use your coding agent normally
export OPENAI_BASE_URL=http://127.0.0.1:8420/v1
claude  # or cursor, windsurf, etc.
```

That's it. Tokens are optimized automatically.

## 🔧 How It Works

TokenSaver applies multiple optimization strategies in order:

| # | Strategy | What It Does | Typical Savings |
|---|----------|-------------|-----------------|
| 1 | **Semantic Cache** | Reuse identical/similar responses | 30-60% |
| 2 | **File Deduplication** | Remove repeated file contents | 10-30% |
| 3 | **Comment Stripping** | Remove code comments from context | 5-15% |
| 4 | **Plugin Strategies** | Custom compression (diffs, imports, tool outputs) | 5-20% |
| 5 | **Smart Routing** | Send simple queries to cheap models | 40-70% |
| 6 | **Budget Guards** | Enforce daily limits, auto-downgrade | Variable |

Combined, these typically save **40-70%** on token costs without noticeable quality loss.

## 📊 Dashboard

Start the proxy with a real-time web dashboard:

```bash
tokensaver serve --dashboard-port 8421
# Open http://127.0.0.1:8421
```

Features:
- Real-time token savings
- Daily cost charts
- Budget utilization
- Strategy status

## 📦 Installation

```bash
# Basic install (core features)
pip install tokensaver

# Full install (all features)
pip install tokensaver[full]

# Development
pip install -e ".[dev]"
```

## 🛠️ CLI Commands

```bash
# Start the proxy server + dashboard
tokensaver serve

# View token usage stats
tokensaver stats

# Show daily cost history
tokensaver history --days 30

# Count tokens in text
tokensaver tokens "Hello, world!"

# Show compression results
tokensaver compress "your code or text here"

# List available models and costs
tokensaver providers

# Compare cost between two models
tokensaver compare gpt-4o gpt-4o-mini --tokens 5000

# Show cheapest model for different sizes
tokensaver cheapest

# Set budget limit
tokensaver budget 20.00

# Check budget status
tokensaver budget-status

# Cache statistics
tokensaver cache-stats

# List loaded plugins
tokensaver plugins

# Get setup instructions
tokensaver setup

# Print shell exports
eval "$(tokensaver env)"

# Reset analytics
tokensaver reset --clear-cache
```

## 🔌 Multi-Provider Support

TokenSaver supports multiple LLM providers:

| Provider | Models | Cost |
|----------|--------|------|
| **OpenAI** | GPT-4o, GPT-4o-mini, GPT-4-turbo | $0.15-30/1K tokens |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3 Haiku, Claude 3 Opus | $0.25-75/1K tokens |
| **Google** | Gemini 1.5 Pro, Gemini 1.5 Flash | $0.075-10.5/1K tokens |
| **Ollama** | Llama 3.1, CodeLlama, DeepSeek Coder | **Free** (local) |

The smart router automatically picks the cheapest model for each request based on complexity.

## 🧩 Plugin System

Custom compression strategies can be added as plugins:

```python
# my_plugin.py
from tokensaver.plugins import CompressionStrategy, StrategyResult

class MyStrategy(CompressionStrategy):
    name = "my_custom"
    description = "My custom compression"
    priority = 40  # Lower = runs first

    def apply(self, messages, token_count_fn):
        # Your compression logic
        return messages, StrategyResult(saved_tokens=0, details="done")
```

Built-in plugins:
- `dedup_tool_outputs` — Remove duplicate tool/function outputs
- `compress_diffs` — Compress large unified diffs
- `summarize_imports` — Summarize long import blocks

## 🛡️ Budget Guards

Automatic budget protection:

| Utilization | Action | Effect |
|-------------|--------|--------|
| < 80% | PASS | No changes |
| 80-95% | DOWNGRADE | Route to cheaper model |
| 95-100% | AGGRESSIVE_COMPRESS | Maximum compression |
| > 100% | BLOCK | Return 429 error |

## 🧩 Integration Examples

### Claude Code

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8420/v1
export OPENAI_API_KEY=your-key
claude
```

### Cursor

1. Open Settings → Models
2. Find "Override OpenAI Base URL"
3. Set to `http://127.0.0.1:8420/v1`

### Python / OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8420/v1",
    api_key="your-key",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## 📊 Monitoring

Every optimized response includes headers:

```
X-TokenSaver-Original-Tokens: 12450
X-TokenSaver-Optimized-Tokens: 4320
X-TokenSaver-Saved: 8130
X-TokenSaver-Strategies: file_dedup,plugin:compress_diffs
```

API endpoints:

```bash
# Stats
curl http://127.0.0.1:8420/tokensaver/stats

# Budget status
curl http://127.0.0.1:8420/tokensaver/budget

# Set budget
curl -X POST http://127.0.0.1:8420/tokensaver/budget/limit \
  -H "Content-Type: application/json" \
  -d '{"limit_usd": 20.0}'

# Clear cache
curl -X POST http://127.0.0.1:8420/tokensaver/cache/clear
```

## ⚙️ Configuration

TokenSaver uses environment variables for configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `TOKENDATA_DIR` | `~/.tokensaver` | Data directory |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Upstream API |
| `OPENAI_API_KEY` | — | API key for upstream |

Or configure via code:

```python
from tokensaver.config import settings

settings.cache.enabled = True
settings.compress.aggressiveness = 0.4  # 0.0 = none, 1.0 = aggressive
settings.router.enabled = True
settings.budget.daily_limit_usd = 20.0
```

## 🧪 Development

```bash
git clone https://github.com/youruser/tokensaver
cd tokensaver
pip install -e ".[dev]"

# Run tests
pytest

# Run with auto-reload
tokensaver serve --reload
```

## 🗺️ Roadmap

- [x] **v0.1** — Core proxy, cache, compression, analytics
- [x] **v0.2** — Smart routing, budget guards, web dashboard
- [x] **v0.3** — Multi-provider support, plugin system
- [ ] **v0.4** — LLMLingua-2 integration for deeper compression
- [ ] **v0.5** — Multi-provider automatic failover + load balancing
- [ ] **v1.0** — Production ready

## 📄 License

MIT
