<div align="center">

<img src="docs/logo.png" alt="ContextWeave" width="72" height="72" />

# ContextWeave

**Proactive semantic context for your codebase — fully local, zero cloud.**

ContextWeave watches your editor, parses your code at the AST level, embeds it with a local model, and surfaces the most relevant context snippets automatically — ranked by both semantic similarity *and* recency — before you even think to ask.

[![VS Code Marketplace](https://img.shields.io/visual-studio-marketplace/v/contextweave.contextweave?color=5C4ECC&label=VS%20Code%20Marketplace&logo=visual-studio-code)](https://marketplace.visualstudio.com/items?itemName=contextweave.contextweave)
[![Tests](https://img.shields.io/badge/tests-121%20passing-22c55e?logo=pytest)](daemon/tests/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)](https://python.org)
[![Node](https://img.shields.io/badge/node-18%2B-brightgreen?logo=node.js)](https://nodejs.org)

</div>

---

> **Demo placeholder** — record a 60-second screen capture showing:
> 1. Save a file → daemon ingests silently in the background
> 2. Get stuck on a bug for 60 seconds → context panel opens automatically
> 3. Click "Copy Context" → paste into Claude → get an answer that references your actual functions

![Demo GIF](docs/demo.gif)

---

## What It Does

Every AI assistant — Claude, Copilot, Gemini — is **reactive and stateless**. You open a chat, re-explain your entire codebase from scratch, ask a question, close the tab. Next session: repeat. ContextWeave solves this.

It runs a local background daemon that:

1. **Watches** every file save in VS Code (debounced, non-blocking)
2. **Parses** code into semantic units — full functions and classes, never half-a-function — using Python's stdlib `ast` and tree-sitter for TypeScript/JavaScript
3. **Embeds** each chunk locally with `nomic-embed-text` via Ollama (768 dims, Apache 2.0, no API key, no cloud)
4. **Stores** chunks and their vectors in a single SQLite file using `sqlite-vec` — zero extra infrastructure
5. **Ranks** retrieved chunks by a combined score: `0.6 × cosine similarity + 0.4 × recency decay` with a 4-hour half-life
6. **Detects** when you've been idle on the same file for 10+ minutes without meaningful progress, and proactively opens the context panel

The VS Code extension never blocks the editor. All heavy work happens in the Python daemon. If the daemon is unreachable for any reason, the extension continues silently.

---

## Features

| Feature | Detail |
|---|---|
| **AST-Level Chunking** | Functions and classes are never split. Python uses stdlib `ast`; TypeScript/JavaScript uses tree-sitter. Syntax errors fall back to a whole-file chunk rather than crashing. |
| **Semantic + Recency Ranking** | `score = 0.6 × cosine_similarity + 0.4 × exp(−λ × hours_since_edit)`. Code you touched 10 minutes ago ranks higher than semantically similar code you haven't touched in days. |
| **Stuck Detection** | Detects 10+ minutes of minimal activity on a single file and proactively surfaces relevant context. State is persisted to SQLite — daemon restarts do not lose it. |
| **Local-First, Privacy-First** | Default embedding via Ollama. Your code never leaves your machine. No telemetry, no API keys required. |
| **Multi-Provider** | Swap between Ollama, OpenAI, Anthropic/Voyage, or LM Studio by changing **one line** in `config.toml`. |
| **Non-Blocking** | The extension sends fire-and-forget `POST /ingest` requests. Embedding happens in a background async queue. No editor lag — ever. |
| **Graceful Shutdown** | SIGINT and SIGTERM are handled. The daemon drains the embedding queue (up to 10 seconds) before exiting. No in-flight work is silently dropped. |
| **121 Tests, No Mocking Compromise** | All 121 tests pass without Ollama running or a real VS Code instance. Every module has a corresponding test file. |

---

## Supported Languages

| Language | Parser | Chunk Types |
|---|---|---|
| Python | stdlib `ast` | `function`, `async function`, `class`, `method` |
| TypeScript | tree-sitter | `function`, `class`, `method`, `arrow function` |
| JavaScript | tree-sitter | `function`, `class`, `method`, `arrow function` |

---

## Quick Start (< 5 minutes)

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.com) installed and running

### 1. Pull the embedding model (one-time, ~274 MB)

```bash
ollama pull nomic-embed-text
```

### 2. Start the daemon

```bash
cd daemon
pip install -e ".[dev]"
python main.py
```

Verify it's running:

```bash
curl http://localhost:7331/health
# {"status":"ok","version":"1.0.0","queue_depth":0,"provider_healthy":true,"db_healthy":true,"chunks_total":0}
```

The database is created at `~/.contextweave/memory.db` on first run.

### 3. Install the VS Code extension

**Option A — from source (development)**

```bash
cd extension
npm install
npm run compile
```

Then in VS Code: `Ctrl+Shift+P` → `Developer: Install Extension from Location...` → select the `extension/` directory.

**Option B — press F5**

Open the `extension/` folder in VS Code and press `F5` to launch an Extension Development Host with ContextWeave loaded.

### 4. Start coding

Open any `.py`, `.ts`, or `.js` file and save it. The extension:

1. Debounces 800ms, then sends the file to the daemon
2. The daemon chunks, embeds, and stores it (background, non-blocking)
3. Open the context panel: `Ctrl+Shift+P` → `ContextWeave: Show Context Panel`
4. See ranked chunks, copy them, or send them directly to your AI

---

## Usage

### Commands

| Command | Description |
|---|---|
| `ContextWeave: Show Context Panel` | Open the ranked context sidebar |
| `ContextWeave: Rank Context for Current File` | Re-run the rank query for the active file |
| `ContextWeave: Check Daemon Health` | Show daemon status in a notification |
| `ContextWeave: Restart Daemon Connection` | Reconnect after restarting the daemon |

### The Context Panel

The sidebar panel shows ranked code chunks with:

- **Score bar** — green (semantic) + yellow (recency) breakdown per chunk
- **📋 Copy Context** — copies all ranked chunks as a formatted `--- CONTEXTWEAVE CONTEXT ---` block, ready to paste into any AI chat
- **🤖 Ask AI** — sends context + query to Copilot Chat (or copies to clipboard if Copilot is not installed)
- **✋ Not Stuck** — dismisses the stuck notification for the current file and resets the detector
- **🔄 Refresh** — re-runs the rank query on demand

### Status Bar

Bottom-right of VS Code shows daemon health at a glance:

| Status | Meaning |
|---|---|
| `✓ CW: OK` | Daemon connected, provider healthy |
| `⚠ CW: Degraded` | Daemon running, LLM provider unreachable |
| `✗ CW: Offline` | Daemon not running |

Health is polled every 30 seconds.

---

## Configuration

### VS Code Extension Settings (`Ctrl+,` → search "contextweave")

| Setting | Default | Description |
|---|---|---|
| `contextweave.daemon.host` | `127.0.0.1` | Daemon host |
| `contextweave.daemon.port` | `7331` | Daemon port |
| `contextweave.daemon.timeout` | `5000` | HTTP timeout (ms) |
| `contextweave.ingest.debounceMs` | `800` | Save debounce delay |
| `contextweave.ingest.languages` | `["python","typescript","javascript"]` | Languages to ingest |
| `contextweave.rank.topK` | `8` | Chunks to surface (max 20) |
| `contextweave.panel.autoRefresh` | `true` | Auto-refresh panel on save |
| `contextweave.autoOpenPanel` | `true` | Open panel when stuck is detected |

### Daemon Configuration (`~/.contextweave/config.toml`)

All daemon config lives in one file. No hardcoded values anywhere in the codebase.

```toml
[daemon]
port                   = 7331
host                   = "127.0.0.1"
log_level              = "INFO"
max_file_size_kb       = 500    # files larger than this are skipped
max_queue_size         = 500    # embedding queue max depth
shutdown_drain_timeout_s = 10   # seconds to drain queue on SIGTERM

[provider]
# Options: "ollama" | "openai" | "anthropic" | "lmstudio"
embed_provider = "ollama"
chat_provider  = "ollama"

[provider.ollama]
base_url    = "http://localhost:11434"
embed_model = "nomic-embed-text"
chat_model  = "llama3.2"
timeout_s   = 30

[provider.openai]
base_url    = "https://api.openai.com/v1"
api_key     = ""                       # reads from OPENAI_API_KEY env var if empty
embed_model = "text-embedding-3-small"
chat_model  = "gpt-4o-mini"
timeout_s   = 30

[provider.anthropic]
api_key     = ""                       # reads from ANTHROPIC_API_KEY env var if empty
embed_model = "voyage-3"               # via Voyage API
chat_model  = "claude-3-5-haiku-20241022"
timeout_s   = 30

[provider.lmstudio]
base_url    = "http://localhost:1234/v1"
api_key     = "lm-studio"             # LM Studio accepts any string
embed_model = "nomic-embed-text-v1.5"
chat_model  = "qwen2.5-7b-instruct"
timeout_s   = 30

[ranker]
semantic_weight        = 0.6    # weight for cosine similarity
recency_weight         = 0.4    # weight for recency decay
recency_half_life_hours = 4.0   # decay half-life
candidate_pool         = 30     # ANN candidates before re-ranking
max_context_tokens     = 6000   # hard cap on injected context size

[stuck_detector]
threshold_seconds  = 600  # 10 minutes of no significant change
min_change_tokens  = 10   # minimum new words to reset the stuck clock
```

**Switching providers** — change the single line `embed_provider = "ollama"` to `embed_provider = "openai"` (or `"anthropic"`, or `"lmstudio"`). That's the entire change.

---

## API Reference

The daemon exposes a local REST API on `127.0.0.1:7331`. All routes are documented at `http://localhost:7331/docs` (auto-generated by FastAPI).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Daemon + provider + DB health. Never returns 500. |
| `POST` | `/ingest` | Chunk and queue a file for embedding. Returns immediately. |
| `GET` | `/rank` | Retrieve top-K semantically + recency ranked chunks for a query. |
| `POST` | `/stuck/dismiss` | Reset stuck state for a file path. |
| `GET` | `/status` | Uptime, total chunks ingested, rank calls, queue depth. |

### `POST /ingest`

```json
// Request
{ "file_path": "/abs/path/to/file.py", "content": "...", "language": "python" }

// Response 200
{ "status": "queued", "chunks": 12, "stuck": false }

// Response 413 — file too large
// Response 422 — unsupported language
// Response 503 — daemon shutting down
```

### `GET /rank?q=handle+authentication&top_k=8`

```json
{
  "query": "handle authentication",
  "chunks": [
    {
      "id": "a1b2c3d4e5f6a7b8",
      "chunk_name": "validate_jwt_token",
      "chunk_type": "function",
      "file_path": "/src/auth/jwt.py",
      "start_line": 42,
      "end_line": 67,
      "content": "def validate_jwt_token(token: str) -> ...",
      "score": 0.847,
      "semantic_score": 0.91,
      "recency_score": 0.74
    }
  ],
  "total_tokens": 1843
}
```

---

## Architecture

ContextWeave is a two-process system. See [**ARCHITECTURE.md**](ARCHITECTURE.md) for the full technical deep-dive, including:

- Why the extension and daemon are separate processes (and what breaks if you run embeddings inside Node.js)
- Why AST chunking beats line-splitting for embedding quality
- Why `sqlite-vec` was chosen over ChromaDB, Pinecone, and FAISS
- Why `nomic-embed-text` over OpenAI `text-embedding-3-small`
- Every decision in the ranking formula: the 0.6/0.4 weights, the 4-hour half-life, and why recency matters as much as similarity
- The non-blocking queue: why `maxsize=500`, why oldest-first eviction, why 2 workers
- Known limitations and what changes at 10× scale

```
┌──────────────────────────────┐       HTTP/JSON        ┌──────────────────────────────┐
│        VS Code Extension     │ ◄────────────────────► │        Python Daemon         │
│                              │                        │                              │
│  extension.ts   (lifecycle)  │   POST /ingest         │  server.py     (FastAPI)     │
│  daemon-client.ts (HTTP)     │   GET  /rank           │  chunker.py    (AST parser)  │
│  context-panel.ts (WebView)  │   GET  /health         │  embedder.py   (async queue) │
│  injector.ts    (clipboard)  │   GET  /status         │  ranker.py     (scoring)     │
│  config.ts      (settings)   │   POST /stuck/dismiss  │  stuck_detector.py (DB FSM)  │
│                              │                        │  db.py         (SQLite+vec)  │
│  Status Bar ← health poll    │                        │  providers/    (LLM layer)   │
└──────────────────────────────┘                        └──────────────────────────────┘
```

---

## Ranking Formula

```
score = (0.6 × semantic_score) + (0.4 × recency_score)

semantic_score = 1.0 − cosine_distance(query_embedding, chunk_embedding)
recency_score  = exp(−λ × hours_since_last_seen)
λ              = ln(2) / recency_half_life_hours   # default half-life: 4 hours
```

**Example:** A chunk accessed 2 hours ago with cosine similarity 0.82:

```
recency_score  = exp(−0.1733 × 2) = 0.707
score          = 0.6 × 0.82 + 0.4 × 0.707 = 0.775
```

Pure semantic retrieval returns globally similar code. Pure recency returns whatever you just typed. The combined formula surfaces code that is both semantically relevant *and* part of your current work session. The 4-hour half-life reflects the observed boundary between "recent work" and "distant work" in a typical coding session.

---

## Project Structure

```
contextweave/
├── daemon/                        # Python FastAPI daemon
│   ├── contextweave/
│   │   ├── __init__.py
│   │   ├── config.py              # Frozen dataclass config + TOML loader
│   │   ├── db.py                  # SQLite + sqlite-vec schema + WAL setup
│   │   ├── models.py              # Pydantic v2 request/response models
│   │   ├── server.py              # FastAPI app, lifespan, all routes
│   │   ├── chunker.py             # AST-level code splitter (Python + tree-sitter)
│   │   ├── embedder.py            # Async queue + 2 background workers
│   │   ├── ranker.py              # Semantic + recency scoring + retrieval
│   │   ├── stuck_detector.py      # DB-persisted idle tracker (survives restarts)
│   │   ├── summarizer.py          # LLM-based chunk summarization
│   │   └── providers/
│   │       ├── base.py            # LLMProvider ABC + EmbedResult + ChatResult
│   │       ├── ollama.py          # Ollama provider
│   │       ├── openai_compat.py   # OpenAI / LM Studio provider
│   │       └── anthropic.py       # Anthropic + Voyage provider
│   ├── tests/
│   │   ├── conftest.py            # Shared fixtures + MockProvider
│   │   ├── test_config.py         # 22 tests
│   │   ├── test_db.py             # 14 tests
│   │   ├── test_server.py         # 22 tests
│   │   ├── test_chunker.py        # 27 tests
│   │   ├── test_embedder.py       # 12 tests
│   │   ├── test_ranker.py         # 18 tests
│   │   └── test_stuck_detector.py # 10 tests (including restart persistence)
│   ├── main.py
│   └── pyproject.toml
├── extension/                     # VS Code extension (TypeScript)
│   ├── src/
│   │   ├── extension.ts           # Activation, file watcher, debounce
│   │   ├── daemon-client.ts       # Typed HTTP client (2s timeout, silent errors)
│   │   ├── context-panel.ts       # WebView sidebar panel
│   │   ├── injector.ts            # Context block formatter + clipboard
│   │   ├── config.ts              # VS Code settings reader
│   │   └── types.ts               # Shared TypeScript types
│   ├── package.json
│   ├── tsconfig.json
│   └── esbuild.config.js
├── ARCHITECTURE.md                # Every design decision, with tradeoffs
└── README.md
```

---

## Running Tests

```bash
cd daemon
pip install -e ".[dev]"
pytest tests/ -v
```

```
======================== 121 passed in 4.32s ========================
```

All 121 tests use a `MockProvider` that returns deterministic embeddings and a temporary in-memory database. **No Ollama, no API keys, no network access required.**

Test naming convention: `test_chunker_falls_back_on_syntax_error`, `test_stuck_detector_state_survives_daemon_restart`, `test_embedder_drops_oldest_when_queue_is_full` — every test name describes exactly what it verifies.

---

## Error Handling

Every failure mode has an explicit, non-crashing code path:

| Failure | Behavior |
|---|---|
| File > 500 KB | Skipped with `WARNING` log. Never crashes. |
| Syntax error in file | Falls back to whole-file chunk (capped at 4000 chars). |
| DB write failure | Logs `ERROR`, continues processing next chunk. |
| Embedding queue full (500 items) | Drops the **oldest** item, accepts the new one. Logs `WARNING`. |
| LLM provider timeout | Retries with exponential backoff: 1s → 2s → 4s. After 4 failures, skips chunk and logs `ERROR`. |
| Port already in use | Fails fast with a clear error message and `exit(1)`. |
| `sqlite-vec` not installed | Fails fast with install instructions. |
| Daemon unreachable from extension | Extension continues silently. Status bar shows `✗ CW: Offline`. |

---

## Provider Abstraction

All LLM interactions go through the `LLMProvider` abstract base class. No provider-specific code appears outside the `providers/` directory.

```python
class LLMProvider(ABC):
    async def embed(self, text: str) -> EmbedResult: ...
    async def chat(self, system: str, user: str) -> ChatResult: ...
    async def health_check(self) -> bool: ...
```

Three implementations ship out of the box:

| Provider | `embed_provider` value | Notes |
|---|---|---|
| Ollama | `"ollama"` | Default. Free, local, no API key. |
| OpenAI / LM Studio | `"openai"` / `"lmstudio"` | Uses the OpenAI-compatible API protocol. |
| Anthropic + Voyage | `"anthropic"` | Embeds via Voyage API, chats via Anthropic Messages API. |

Adding a new provider: create one file in `providers/`, implement three methods, add a config key. No changes anywhere else.

---

## Known Limitations

These are documented honestly. An architecture without known limitations is an architecture that hasn't been examined.

1. **Single-machine only.** The daemon binds to `127.0.0.1`. No TLS, no auth. Intentional for a dev tool — this is not a production server.
2. **No incremental re-embedding.** A single-line change in a 200-line function re-embeds the whole function. Content dedup skips truly unchanged chunks, but any modification triggers a full re-embed of that chunk.
3. **Token estimation is approximate.** The `words × 1.33` heuristic can over- or under-count by ~20%. A proper tokenizer (`tiktoken`) would be more accurate but adds a dependency.
4. **No cross-file ranking signals.** The ranker does not consider call graphs, imports, or co-editing patterns. Functions in the same call chain as the current file get no ranking boost. This is planned for a future phase.
5. **Tree-sitter language support.** Only Python, TypeScript, and JavaScript are supported. Adding a new language requires adding its tree-sitter grammar package and a node-type mapping in `chunker.py`.
6. **No garbage collection.** Deleted files, renamed functions, and stale chunks are never removed. A GC sweep comparing `chunks.file_path` against the filesystem would fix this. It is not yet implemented.
7. **Minified JavaScript.** A minified file produces one enormous chunk that is useless for retrieval. These should be filtered by detecting single-line files above a token threshold.

---

## Scaling Roadmap

What changes when this needs to handle 10× the load:

1. **Batch embedding** — embed 8–16 chunks per API call instead of one. Reduces HTTP overhead by ~90%.
2. **Incremental AST diffing** — diff the new AST against the previous to re-embed only changed chunks, reducing embedding calls from O(n) to O(changed).
3. **Persistent embedding cache** — cache by content hash. Duplicate code (shared utilities, copy-pasted functions) gets embedded once.
4. **Multi-language expansion** — tree-sitter grammars for Go, Rust, Java, C++, Ruby. The chunker architecture already supports this.
5. **Cross-file signal graph** — a lightweight dependency graph from imports and function calls. Boost ranking scores for chunks in the same call chain.
6. **Streaming ingest** — replace fire-and-forget `POST` with a WebSocket diff stream. Sub-second context updates as you type.
7. **Multi-workspace support** — add a `workspace_id` column to the `chunks` table. One daemon, multiple isolated VS Code windows.

---

## Tech Stack

**Daemon (Python 3.11+)**

| Package | Reason |
|---|---|
| `fastapi` | Async HTTP, minimal overhead, auto-generated OpenAPI docs |
| `uvicorn` | ASGI server, production-grade, handles graceful shutdown |
| `sqlite-vec` | Vector search inside SQLite — zero infrastructure, WAL-safe concurrent reads |
| `httpx` | Async HTTP client for all LLM provider calls |
| `tree-sitter` | AST parsing for TypeScript and JavaScript |
| `pydantic v2` | Data validation and typed API models |
| `tomllib` | TOML config parsing (Python 3.11+ stdlib, no extra dependency) |
| `structlog` | Structured JSON logging. No `print()` statements anywhere. |
| `pytest` + `pytest-asyncio` | Test runner with async test support |

**Extension (TypeScript)**

| Package | Reason |
|---|---|
| VS Code Extension API | File events, WebView, status bar, command palette |
| `esbuild` | Fast bundler — not webpack |
| Native `fetch` (Node 18+) | HTTP calls to daemon — no extra HTTP library needed |

**Embedding model**

- **Default:** `nomic-embed-text` via Ollama — 768 dims, Apache 2.0 license, fully local, free, MTEB score 0.627
- **Optional:** `text-embedding-3-small` (OpenAI), `voyage-3` (Anthropic/Voyage), or any model your LM Studio instance serves

Why `nomic-embed-text` over OpenAI embeddings: it runs locally (no API cost, no code leaves your machine), Apache 2.0 license, and its MTEB retrieval score (0.627) slightly exceeds `text-embedding-3-small` (0.620) while being completely free.

---

## Database Schema

Four tables, all in a single file at `~/.contextweave/memory.db`. WAL mode enabled. Foreign keys on.

```sql
-- One row per semantic unit (function, class, method, module)
CREATE TABLE chunks (
    id           TEXT PRIMARY KEY,   -- sha256(file_path + ":" + chunk_name)[:16]
    file_path    TEXT NOT NULL,
    chunk_name   TEXT NOT NULL,
    chunk_type   TEXT NOT NULL CHECK(chunk_type IN ('function','class','method','module')),
    content      TEXT NOT NULL,
    language     TEXT NOT NULL,
    start_line   INTEGER NOT NULL,
    end_line     INTEGER NOT NULL,
    last_seen    REAL NOT NULL,       -- unix timestamp, updated on every ingest
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);

-- Vector index — joined to chunks by rowid (integer join, not text join)
CREATE VIRTUAL TABLE chunk_vectors USING vec0(embedding FLOAT[768]);

-- Recency tracking — updated every time a chunk is returned by /rank
CREATE TABLE access_log (
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    accessed_at REAL NOT NULL,
    PRIMARY KEY (chunk_id, accessed_at)
);

-- Stuck detector state — persisted across daemon restarts
CREATE TABLE stuck_state (
    file_path               TEXT PRIMARY KEY,
    last_content_hash       TEXT NOT NULL,
    last_significant_change REAL NOT NULL,
    stuck_notified          INTEGER NOT NULL DEFAULT 0
);
```

---

## Contributing

Contributions are welcome. Before opening a PR:

1. Run the full test suite: `pytest tests/ -v` — all 121 tests must pass
2. No `print()` statements — use `structlog` at the appropriate level
3. No bare `except:` — always catch specific exceptions
4. No hardcoded URLs, ports, or model names outside `config.py`
5. Every new public function needs a docstring and full type annotations

---

## Author

Aryan Bhati

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

Built to make every AI assistant smarter about your codebase — without sending a single line of your code to the cloud.

</div>
