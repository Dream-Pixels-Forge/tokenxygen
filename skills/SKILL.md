# Tokenxygen Skill

> **Tokenxygen** — Universal token optimizer for coding agents. Save 40-70% on LLM costs with zero code changes.

## What is Tokenxygen?

Tokenxygen is a drop-in proxy that sits between your coding agent (Claude Code, Cursor, Windsurf, Codex) and LLM APIs, automatically optimizing tokens in-flight. It applies multiple compression and optimization strategies to reduce your token usage without sacrificing quality.

```
┌─────────────┐     ┌────────────────┐     ┌──────────┐
│  Coding      │────▶│  Tokenxygen    │────▶│  OpenAI  │
│  Agent       │◀────│  Proxy         │◀────│  API     │
└─────────────┘     └────────────────┘     └──────────┘
                    🎯 Cache | Compress | Route | Budget
```

## Quick Start

```bash
# Install
pip install tokenxygen

# Start the proxy
tokenxygen serve

# Point your tool to the proxy
export OPENAI_BASE_URL=http://127.0.0.1:8420/v1

# Use your coding agent normally
claude  # or cursor, windsurf, etc.

# Check savings
tokenxygen stats
```

## Features

### 1. Semantic Cache
Stores and reuses responses for identical or similar prompts. First request goes to the API, subsequent similar requests are served from cache instantly.

**Savings:** 30-60% on repeated queries

```bash
# Check cache stats
tokenxygen cache-stats

# Clear cache
curl -X POST http://127.0.0.1:8420/tokenxygen/cache/clear
```

### 2. Prompt Compression
Multi-strategy compression optimized for coding contexts:

| Strategy | What It Does |
|----------|-------------|
| File Deduplication | Remove repeated file contents |
| Comment Stripping | Remove code comments from context |
| Whitespace Normalization | Collapse excessive whitespace |
| Block Collapse | Remove repeated context blocks |
| Context Truncation | Keep only relevant context |

**Savings:** 10-30%

```bash
# See compression results
tokenxygen compress "your code here"

# Deep compression with LLMLingua-2
tokenxygen deep-compress "long text here"
```

### 3. Smart Router
Classifies prompts by complexity and routes to the cheapest capable model:

| Tier | Prompt Type | Routes To |
|------|-------------|-----------|
| SIMPLE | Greetings, yes/no | gpt-4o-mini |
| MEDIUM | Code questions, explanations | gpt-4o-mini |
| COMPLEX | Architecture, security | gpt-4o |
| EXPERT | Multi-step, critical | gpt-4o |

**Savings:** 40-70%

```bash
# See available models and costs
tokenxygen providers

# Compare two models
tokenxygen compare gpt-4o gpt-4o-mini --tokens 5000

# Show cheapest model by size
tokenxygen cheapest
```

### 4. Budget Guards
Automatic daily spending protection:

| Utilization | Action | Effect |
|-------------|--------|--------|
| < 80% | PASS | No changes |
| 80-95% | DOWNGRADE | Route to cheaper model |
| 95-100% | AGGRESSIVE_COMPRESS | Maximum compression |
| > 100% | BLOCK | Return 429 error |

```bash
# Set daily budget
tokenxygen budget 20.00

# Check budget status
tokenxygen budget-status
```

### 5. Plugin System
Custom compression strategies:

```python
# my_plugin.py
from tokenxygen.plugins import CompressionStrategy, StrategyResult

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

```bash
# List loaded plugins
tokenxygen plugins
```

### 6. Multi-Provider Support
Route to the cheapest provider:

| Provider | Models | Cost |
|----------|--------|------|
| **OpenAI** | GPT-4o, GPT-4o-mini | $0.15-10/1K tokens |
| **Anthropic** | Claude 3.5 Sonnet, Haiku | $0.25-15/1K tokens |
| **Google** | Gemini 1.5 Pro, Flash | $0.075-3.5/1K tokens |
| **Ollama** | Llama 3.1, CodeLlama | **Free** (local) |

### 7. Failover & Load Balancing
Automatic provider switching with circuit breaker:

```python
from tokenxygen.providers.failover import ProviderPool, LoadBalanceStrategy

pool = ProviderPool(
    primary_provider=Provider.OPENAI,
    fallback_providers=[Provider.ANTHROPIC, Provider.OLLAMA],
    config=FailoverConfig(strategy=LoadBalanceStrategy.COST_FIRST),
)
```

```bash
# Show failover pool status
tokenxygen failover
```

## Integration Guides

### Claude Code

```bash
# Option 1: env var
export OPENAI_BASE_URL=http://127.0.0.1:8420/v1
export OPENAI_API_KEY=your-key
claude

# Option 2: use tokenxygen env
eval "$(tokenxygen env)"
claude
```

### Cursor

1. Open Settings → Models
2. Find "Override OpenAI Base URL"
3. Set to `http://127.0.0.1:8420/v1`

### Windsurf

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8420/v1
windsurf
```

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

## CLI Reference

```bash
# Core
tokenxygen serve [OPTIONS]        Start proxy + dashboard
  --host TEXT                     Bind host (default: 127.0.0.1)
  --port INTEGER                  Bind port (default: 8420)
  --dashboard-port INTEGER        Dashboard port (default: 8421)
  --upstream TEXT                 Override upstream API base URL
  --json-logs                     Use JSON log format
  --log-level TEXT                Log level (default: INFO)

# Analytics
tokenxygen stats                 Token usage statistics
tokenxygen history [--days N]    Daily cost history
tokenxygen metrics               Show Prometheus metrics

# Compression
tokenxygen tokens TEXT           Count tokens in text
tokenxygen compress TEXT         Show compression results
tokenxygen deep-compress TEXT    LLMLingua-2 compression

# Models
tokenxygen providers             List all models and costs
tokenxygen compare A B [--tokens N]  Compare two models
tokenxygen cheapest              Cheapest model by size

# Budget
tokenxygen budget LIMIT_USD      Set daily budget
tokenxygen budget-status         Check budget status

# Cache
tokenxygen cache-stats           Cache statistics

# Plugins
tokenxygen plugins               List loaded plugins

# Failover
tokenxygen failover              Failover pool status

# Setup
tokenxygen setup                 Setup instructions
tokenxygen env                   Print shell exports

# Maintenance
tokenxygen reset [--clear-cache] Reset analytics
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TOKENDATA_DIR` | `~/.tokenxygen` | Data directory |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Upstream API |
| `OPENAI_API_KEY` | — | API key for upstream |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama host |

### Programmatic Configuration

```python
from tokenxygen.config import settings

settings.cache.enabled = True
settings.compress.aggressiveness = 0.4  # 0.0 = none, 1.0 = aggressive
settings.router.enabled = True
settings.budget.daily_limit_usd = 20.0
```

## Docker Deployment

```bash
# Quick start
cp .env.example .env
# Edit .env with your API keys
docker compose up -d

# Services:
# - Proxy: http://localhost:8420
# - Dashboard: http://localhost:8421
# - Prometheus: http://localhost:9091
```

## Monitoring

### Response Headers

Every optimized response includes:

```
X-Tokenxygen-Original-Tokens: 12450
X-Tokenxygen-Optimized-Tokens: 4320
X-Tokenxygen-Saved: 8130
X-Tokenxygen-Strategies: file_dedup,plugin:compress_diffs
```

### API Endpoints

```bash
# Stats
curl http://127.0.0.1:8420/tokenxygen/stats

# Budget
curl http://127.0.0.1:8420/tokenxygen/budget

# Metrics (Prometheus)
curl http://127.0.0.1:8420/metrics

# Health
curl http://127.0.0.1:8420/health
```

### Web Dashboard

```bash
tokenxygen serve --dashboard-port 8421
# Open http://127.0.0.1:8421
```

## Troubleshooting

### Common Issues

**Port already in use:**
```bash
tokenxygen serve --port 8421
export OPENAI_BASE_URL=http://127.0.0.1:8421/v1
```

**API key not working:**
```bash
# Make sure your API key is set
export OPENAI_API_KEY=sk-your-key-here
tokenxygen serve
```

**Cache not working:**
```bash
# Check cache stats
tokenxygen cache-stats

# Clear cache if needed
curl -X POST http://127.0.0.1:8420/tokenxygen/cache/clear
```

**High latency:**
```bash
# Disable compression for speed
export TOKENXYGEN_COMPRESS_ENABLED=false
tokenxygen serve

# Or reduce aggressiveness
export TOKENXYGEN_COMPRESS_AGGRESSIVENESS=0.1
```

### Debug Mode

```bash
# Enable debug logging
tokenxygen serve --log-level DEBUG --json-logs

# Check logs
tail -f ~/.tokenxygen/logs/tokenxygen.log
```

## Performance

Typical performance impact:

| Metric | Value |
|--------|-------|
| Latency overhead | < 5ms |
| Cache hit latency | < 1ms |
| Memory usage | ~50MB |
| CPU usage | < 1% |

## License

MIT
