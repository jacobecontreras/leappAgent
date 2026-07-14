# LEAPP Custom ReAct Agent

> **DISCLAIMER:** This tool is a proof-of-concept designed strictly for educational purposes and data location assistance. It is **not** a substitute for manual data verification or forensic conclusions. All outputs must be verified against the original evidence.

## Purpose

This project explores the mechanics of AI agents within a forensic context. Its primary utility is to assist in locating evidence within LEAPP reports.

The system pairs a staged agent pipeline, written from scratch, with read-only SQL access to the LAVA artifact database that modern LEAPP tools produce. A router classifies each question, the pipeline inspects the relevant artifact schemas deterministically, and the model writes SQL against the report's own data - with error-grounded retries and a hard gate that refuses to answer evidence questions when no query succeeded. Vague content questions fall back to semantic search, and open-ended investigations to a bounded ReAct loop.

## Forensic posture

- **Fully local:** all inference runs through [Ollama](https://ollama.com) on localhost. Nothing leaves the machine - there are no API keys, no cloud calls, and the app binds to 127.0.0.1 only.
- **Evidence is never copied or modified:** the agent queries the report's `_lava_artifacts.db` directly through a connection that physically cannot write (SQLite `mode=ro` + `query_only` + an authorizer that rejects everything except reads). Only a single SELECT statement per query is accepted.
- **Evidence integrity:** the LAVA database and manifest are SHA-256 hashed at ingest and recorded in a manifest table, so the source report can be re-verified at any time.
- **Auditability:** every session writes a JSONL audit trail (`backend/logs/audit/`) recording user messages, each tool call with its arguments and result - including the exact SQL of every query, making the analysis reproducible - plus semantic-search retrievals, the model used, and timestamps.
- **Untrusted contents:** report data (messages, filenames) is treated as evidence, never as instructions to the agent.

## Features

- **Staged pipeline:** question routing, schema inspection, SQL generation, and retry logic are fixed code paths - the model makes only the decisions it is good at (classification and SQL). Unroutable questions fall back to a hand-written, bounded ReAct loop using Ollama's native tool calling.
- **Text-to-SQL tools:** the pipeline inspects a table's columns, types, and sample rows before querying (`describeArtifact`), runs guarded read-only SQL (`queryArtifacts`), and can hunt a value across every artifact table at once (`searchArtifacts`).
- **Anti-hallucination gate:** answers to evidence questions are refused in code when no query or search succeeded - the model cannot answer from memory.
- **Scoped RAG pipeline:** free-text columns (messages, notes, titles) are embedded via a local Ollama embedding model into a persistent ChromaDB store for semantic search; structured data is served by SQL, not vectors.
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
ollama pull gpt-oss:20b
ollama pull nomic-embed-text

# Install dependencies
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt

# Run
backend/venv/bin/python app.py
```

The app opens a native window, detects installed Ollama models, and picks sensible defaults (changeable in settings). Upload an aLEAPP/iLEAPP report directory and start asking questions.

Reports must be in the LAVA format (containing `_lava_artifacts.db` and `_lava_data.lava` or `_lava_data.json`), which iLEAPP v2.x and aLEAPP v3.4+ produce by default. Older TSV-only reports are not supported.

Note: on Linux, pywebview needs the system webview packages (`python3-gi` and WebKit2GTK via your package manager).

## Tests

```bash
backend/venv/bin/pip install -r backend/requirements-dev.txt
backend/venv/bin/python -m pytest
```
