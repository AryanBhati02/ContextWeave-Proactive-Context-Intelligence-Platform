# ContextWeave

Proactive ambient context engine for developers. A daemon that watches your code, understands it at the AST level, and surfaces the most relevant context before you even ask.

## Architecture

Two-process design:

- **Python FastAPI daemon** — chunking, embedding, ranking, stuck detection
- **VS Code extension** — captures file events, renders context panel

Communication: local HTTP on `127.0.0.1:7331`.

## Quick Start

```bash
cd daemon
pip install -e ".[dev]"
python main.py
```

## Configuration

All config lives in `~/.contextweave/config.toml` (created automatically on first run).

## Testing

```bash
cd daemon
pytest tests/ -v
```
