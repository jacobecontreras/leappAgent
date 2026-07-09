# LEAPP RAG + Custom ReAct Agent

> **DISCLAIMER:** This tool is a proof-of-concept designed strictly for educational purposes and data location assistance. It is **not** a substitute for manual data verification or forensic conclusions. All outputs must be verified against the original evidence.

## Purpose

This project explores the mechanics of AI agents within a forensic context. Its primary utility is to assist in locating evidence within LEAPP reports.

The system utilizes a RAG (Retrieval-Augmented Generation) architecture combined with a custom ReAct (Reasoning + Acting) agent, written from scratch, to parse and interact with report data.

## Forensic posture

- **Fully local:** all inference runs through [Ollama](https://ollama.com) on localhost. Nothing leaves the machine - there are no API keys, no cloud calls, and the app binds to 127.0.0.1 only.
- **Evidence integrity:** every source file (TSV exports, timeline database) is SHA-256 hashed at ingest and recorded in an ingest manifest, so the source report can be shown to be unmodified. Reports are only ever opened read-only.
- **Auditability:** every session writes a JSONL audit trail (`backend/logs/audit/`) recording user messages, each tool call with its arguments and result, semantic-search retrievals with chunk IDs and distances, the model used, and timestamps.

## Features

- **Custom ReAct agent:** a hand-written reasoning loop using Ollama's native tool calling. Tools include artifact listing, paginated artifact data, pattern search, and semantic search over embedded report data.
- **RAG pipeline:** report rows are embedded via a local Ollama embedding model into a persistent ChromaDB store.
- **Transparent reasoning:** the chat streams the agent's thinking and tool calls into a collapsible per-message process view.

## Tech stack

- **Backend:** Python, FastAPI, ChromaDB, httpx
- **LLM:** Ollama (local), native tool calling
- **Shell:** pywebview (native window on macOS/Windows/Linux, no bundled browser)
- **Frontend:** vanilla HTML/CSS/JavaScript served by FastAPI

## Setup

Requires Python 3.11+ and [Ollama](https://ollama.com/download).

```bash
# Pull a tool-capable chat model and an embedding model
ollama pull qwen3
ollama pull nomic-embed-text

# Install dependencies
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt

# Run
backend/venv/bin/python app.py
```

The app opens a native window, detects installed Ollama models, and picks sensible defaults (changeable in settings). Upload an aLEAPP/iLEAPP report directory (one containing `_TSV Exports` and `_Timeline`) and start asking questions.

Note: on Linux, pywebview needs the system webview packages (`python3-gi` and WebKit2GTK via your package manager).

## Tests

```bash
backend/venv/bin/pip install -r backend/requirements-dev.txt
backend/venv/bin/python -m pytest
```
