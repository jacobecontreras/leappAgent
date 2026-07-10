import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from database.database import get_db_cursor
from services.ollama_client import ollama_client
from services.system_prompt import ROUTER_PROMPT, SQL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

ROUTES = ("structured_query", "text_search", "semantic_search", "exploratory", "direct")
MAX_ROUTER_TABLES = 3
CATALOG_DESCRIPTION_CHARS = 120

ROUTER_FORMAT = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": list(ROUTES)},
        "tables": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_ROUTER_TABLES},
        "query_text": {"type": "string"}
    },
    "required": ["route", "tables", "query_text"]
}

SQL_FORMAT = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"]
}


@dataclass
class Route:
    route: str
    tables: List[str]
    query_text: str


def resolve_job(explicit_job_name: Optional[str]) -> Optional[str]:
    """Explicit job wins; otherwise the most recently uploaded completed report"""
    if explicit_job_name:
        return explicit_job_name
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT job_name FROM reports WHERE status = 'completed' ORDER BY upload_date DESC LIMIT 1")
        row = cursor.fetchone()
    return row[0] if row else None


def load_catalog(job_name: str) -> List[dict]:
    with get_db_cursor() as cursor:
        cursor.execute("""
            SELECT category, artifact_name, tablename, description, record_count, source_path
            FROM artifact_catalog WHERE job_name = ?
            ORDER BY category, artifact_name
        """, (job_name,))
        return [
            {"category": row[0], "artifact_name": row[1], "tablename": row[2],
             "description": row[3], "record_count": row[4], "source_path": row[5]}
            for row in cursor.fetchall()
        ]


def render_catalog(rows: List[dict]) -> str:
    """One line per artifact: tablename | name | category | rows | description"""
    lines = ["tablename | artifact | category | rows | description"]
    for row in rows:
        description = (row.get("description") or "")[:CATALOG_DESCRIPTION_CHARS]
        lines.append(f"{row['tablename']} | {row['artifact_name']} | {row['category']} | "
                     f"{row['record_count']} | {description}")
    return "\n".join(lines)


def _think_level(chat_model: str) -> Optional[str]:
    """Low reasoning effort for gpt-oss router/SQL turns; omit for other models"""
    return "low" if chat_model.startswith("gpt-oss") else None


async def complete(chat_model: str, messages: list, format: Optional[dict] = None,
                   think: Optional[str] = None) -> str:
    """Consume a chat_stream into a single content string (thinking discarded)"""
    content = ""
    async for chunk in ollama_client.chat_stream(chat_model, messages, format=format, think=think):
        content += chunk.content
    return content


def _extract_json(raw: str) -> Optional[dict]:
    """Lenient JSON extraction: take the outermost {...} slice, ignore fences/prose"""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_route(raw: str, catalog_tablenames: List[str]) -> Optional[Route]:
    """Parse router output; None means fall back to the exploratory loop"""
    parsed = _extract_json(raw)
    if not parsed or parsed.get("route") not in ROUTES:
        return None
    tables = parsed.get("tables")
    if not isinstance(tables, list):
        tables = []
    known = set(catalog_tablenames)
    tables = [t for t in tables if isinstance(t, str) and t in known][:MAX_ROUTER_TABLES]
    query_text = parsed.get("query_text")
    if not isinstance(query_text, str):
        query_text = ""
    return Route(route=parsed["route"], tables=tables, query_text=query_text)


async def route_question(chat_model: str, prompt: str, catalog_text: str,
                         history: list, catalog_tablenames: List[str]) -> tuple:
    """Stage 1: classify the question. Returns (Route | None, raw model output)"""
    messages = [{"role": "system", "content": ROUTER_PROMPT + catalog_text}]
    messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    raw = await complete(chat_model, messages, format=ROUTER_FORMAT, think=_think_level(chat_model))
    return parse_route(raw, catalog_tablenames), raw


async def generate_sql(chat_model: str, question: str, describes: List[dict],
                       history: list, feedback: Optional[str] = None) -> Optional[str]:
    """Stage 3: single-turn SQL generation from schemas + sample rows"""
    schema_block = json.dumps(describes, default=str)
    user_content = f"Question: {question}\n\nSchemas and sample rows:\n{schema_block}"
    if feedback:
        user_content += f"\n\nFeedback on your previous query:\n{feedback}"

    messages = [{"role": "system", "content": SQL_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    raw = await complete(chat_model, messages, format=SQL_FORMAT, think=_think_level(chat_model))
    parsed = _extract_json(raw)
    if not parsed or not isinstance(parsed.get("sql"), str) or not parsed["sql"].strip():
        logger.warning(f"Unparseable SQL generation output: {raw[:200]}")
        return None
    return parsed["sql"].strip()
