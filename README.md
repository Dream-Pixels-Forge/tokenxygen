# 🚀 TokenSaver

**Universal token optimizer for coding agents — save 40-70% on LLM costs.**

TokenSaver is a drop-in proxy that sits between your coding agent (Claude Code, Cursor, Windsurf, Codex) and LLM APIs, automatically optimizing tokens in-flight. Zero code changes required.

```
┌─────────────┐     ┌────────────────┐     ┌──────────┐
│  Coding      │────▶│  TokenSaver    │────▶│  OpenAI  │
│  Agent       │◀────│  Proxy         │◀────│  API     │
└─────────────┘     └────────────────┘     └──────────┘
                    🎯 Cache | Compress | Route
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

TokenSaver applies 5 optimization strategies in order:

| # | Strategy | What It Does | Typical Savings |
|---|----------|-------------|-----------------|
| 1 | **Semantic Cache** | Reuse identical/similar responses | 30-60% |
| 2 | **File Deduplication** | Remove repeated file contents | 10-30% |
| 3 | **Comment Stripping** | Remove code comments from context | 5-15% |
| 4 | **Whitespace Norm** | Collapse excessive whitespace | 2-5% |
| 5 | **Context Truncation** | Keep only relevant context | 10-40% |

Combined, these typically save **40-70%** on token costs without noticeable quality loss.

## 📦 Installation

```bash
# Basic install (core features)
pip install tokensaver

# With semantic caching (recommended)
pip install tokensaver[cache]

# Full install (cache + compression)
pip install tokensaver[full]

# Development
pip install -e ".[dev]"
```

## 🛠️ CLI Commands

```bash
# Start the proxy server
tokensaver serve --port 8420

# View token usage stats
tokensaver stats

# Show daily cost history
tokensaver history --days 30

# Count tokens in text
tokensaver tokens "Hello, world!"

# Get setup instructions
tokensaver setup

# Print shell exports
eval "$(tokensaver env)"

# Reset analytics
tokensaver reset --clear-cache
```

## 🧩 Integration Examples

### Claude Code

```bash
# Option 1: env var
export OPENAI_BASE_URL=http://127.0.0.1:8420/v1
export OPENAI_API_KEY=your-key
claude

# Option 2: use tokensaver env
eval "$(tokensaver env)"
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

### cURL

```bash
curl http://127.0.0.1:8420/v1/chat/completions \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello!"}]}'
```

## 📊 Monitoring

Every optimized response includes headers:

```
X-TokenSaver-Original-Tokens: 12450
X-TokenSaver-Optimized-Tokens: 4320
X-TokenSaver-Saved: 8130
X-TokenSaver-Strategies: file_dedup,comment_strip
```

View stats anytime:

```bash
tokensaver stats
# → Today: 47 requests, 580K tokens saved, $1.45 saved
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

- [ ] **v0.2** — Smart model routing (classify prompt → cheapest model)
- [ ] **v0.3** — Budget guards with auto-downgrade
- [ ] **v0.4** — Web dashboard with cost analytics
- [ ] **v0.5** — LLMLingua-2 integration for deeper compression
- [ ] **v0.6** — Plugin system for custom compression strategies
- [ ] **v1.0** — Production ready

## 📄 License

MIT
