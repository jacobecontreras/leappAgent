import json
import logging
from typing import AsyncGenerator, Optional

from tools import execute_tool
from tools.ollama_schemas import get_ollama_tools
from services import pipeline
from services.ollama_client import ollama_client
from services.session_manager import session_manager
from services.system_prompt import (DIRECT_PROMPT, NO_REPORT_PROMPT, REACT_SYSTEM_PROMPT,
                                    REFUSAL_MESSAGE, SYNTHESIS_PROMPT, ZERO_ROWS_HINT)
from services.settings_service import settings_service
from logs.audit import audit_logger

logger = logging.getLogger(__name__)

REACT_MAX_ITERATIONS = 8
MAX_SQL_ATTEMPTS = 3
SYNTHESIS_MAX_ROWS = 50
TOOL_RESULT_SUMMARY_LIMIT = 2000
MAX_ITERATIONS_MESSAGE = "I've reached the maximum number of steps. Please try a more specific question."


def _event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload})


class AgentService:
    def _run_tool(self, name: str, arguments: dict, job_name: Optional[str],
                  session_id: str, chat_model: str, stage) -> tuple:
        """Execute one tool call, audit it, and return (events, result)"""
        if job_name and "job_name" not in arguments:
            arguments["job_name"] = job_name

        audit_logger.log(session_id, chat_model, "tool_call",
                         {"stage": stage, "name": name, "arguments": arguments})

        result = execute_tool(name, arguments)
        success = bool(result.get("success", True))

        audit_logger.log(session_id, chat_model, "tool_result", {
            "name": name,
            "success": success,
            "result_summary": json.dumps(result, default=str)[:TOOL_RESULT_SUMMARY_LIMIT],
            "count": result.get("count")
        })

        if name == "semanticSearch" and success:
            audit_logger.log(session_id, chat_model, "retrieval", {
                "query": arguments.get("query"),
                "n_results": len(result.get("results", [])),
                "chunk_ids": [r.get("id") for r in result.get("results", [])],
                "distances": [r.get("distance") for r in result.get("results", [])],
                "embed_model": settings_service.get_embed_model()
            })

        events = [
            _event("tool_call", name=name, arguments=arguments),
            _event("tool_result", name=name, success=success,
                   summary=json.dumps(result, default=str)[:TOOL_RESULT_SUMMARY_LIMIT])
        ]
        return events, result

    def _build_evidence_block(self, question: str, evidence: list, catalog: list) -> str:
        """Serialize executed queries/searches plus source paths for synthesis"""
        used_tables = {t for item in evidence for t in item.get("tables", [])}
        sources = [
            {"artifact": row["artifact_name"], "tablename": row["tablename"],
             "source_path": row["source_path"]}
            for row in catalog if row["tablename"] in used_tables
        ]
        parts = [f"Question: {question}"]
        for item in evidence:
            parts.append(f"\n{item['label']}:\n{json.dumps(item['data'], default=str)}")
        if sources:
            parts.append(f"\nEvidence sources:\n{json.dumps(sources)}")
        return "\n".join(parts)

    def _cap_query_result(self, result: dict) -> dict:
        """Cap serialized rows fed to synthesis; note the truncation in-band"""
        rows = result.get("rows")
        if isinstance(rows, list) and len(rows) > SYNTHESIS_MAX_ROWS:
            capped = dict(result)
            capped["rows"] = rows[:SYNTHESIS_MAX_ROWS]
            capped["note"] = f"showing first {SYNTHESIS_MAX_ROWS} of {len(rows)} returned rows"
            return capped
        return result

    async def process_agent_message(self, prompt: str, session_id: str,
                                    job_name: str = None) -> AsyncGenerator[str, None]:
        """Staged pipeline: route -> describe -> SQL/search with retry -> gated synthesis.

        Falls back to a bounded ReAct loop for exploratory or unroutable questions.
        """
        chat_model = settings_service.get_chat_model()
        if not chat_model:
            yield _event("error", message="No chat model configured. Open settings and select an installed Ollama model.")
            return

        audit_logger.log(session_id, chat_model, "user_message", {"message": prompt})
        history = session_manager.get_context_for_ai(session_id)

        try:
            resolved_job = pipeline.resolve_job(job_name)
            audit_logger.log(session_id, chat_model, "job_resolved",
                             {"job_name": resolved_job, "explicit": bool(job_name)})

            if not resolved_job:
                messages = [{"role": "system", "content": NO_REPORT_PROMPT}] + history + [
                    {"role": "user", "content": prompt}]
                async for event in self._finish(chat_model, messages, session_id, prompt):
                    yield event
                return

            catalog = pipeline.load_catalog(resolved_job)
            catalog_text = pipeline.render_catalog(catalog)
            tablenames = [row["tablename"] for row in catalog]

            route, raw = await pipeline.route_question(chat_model, prompt, catalog_text,
                                                       history, tablenames)
            audit_logger.log(session_id, chat_model, "route", {
                "route": route.route if route else None,
                "tables": route.tables if route else [],
                "query_text": route.query_text if route else "",
                "raw": raw[:500],
                **({} if route else {"fallback_reason": "unparseable"})
            })

            if route is None or route.route == "exploratory":
                async for event in self._react_loop(prompt, session_id, resolved_job,
                                                    chat_model, catalog_text, history):
                    yield event
                return

            yield _event("route", route=route.route, tables=route.tables, job_name=resolved_job)

            if route.route == "direct":
                messages = [{"role": "system", "content": DIRECT_PROMPT + catalog_text}] + history + [
                    {"role": "user", "content": prompt}]
                async for event in self._finish(chat_model, messages, session_id, prompt):
                    yield event
                return

            # Evidence routes: gather via SQL or search, then synthesize behind the gate
            evidence = []
            if route.route == "structured_query":
                async for event in self._structured_query(prompt, route, resolved_job, session_id,
                                                          chat_model, history, evidence):
                    yield event
                if evidence and evidence[0].get("fallback"):
                    async for event in self._react_loop(prompt, session_id, resolved_job,
                                                        chat_model, catalog_text, history):
                        yield event
                    return
            else:
                tool_name = "searchArtifacts" if route.route == "text_search" else "semanticSearch"
                arg_key = "pattern" if route.route == "text_search" else "query"
                query_text = route.query_text or prompt
                events, result = self._run_tool(tool_name, {arg_key: query_text},
                                                resolved_job, session_id, chat_model, route.route)
                for event in events:
                    yield event
                if result.get("success"):
                    matched = []
                    for r in result.get("results", []):
                        if not isinstance(r, dict):
                            continue
                        # searchArtifacts puts tablename top-level; semanticSearch in metadata
                        tablename = r.get("tablename") or (r.get("metadata") or {}).get("tablename")
                        if tablename:
                            matched.append(tablename)
                    evidence.append({"label": f"{tool_name}('{query_text}') results",
                                     "data": result, "tables": matched})

            if not evidence:
                audit_logger.log(session_id, chat_model, "gate_refusal",
                                 {"route": route.route, "attempts": MAX_SQL_ATTEMPTS})
                yield _event("final", content=REFUSAL_MESSAGE)
                audit_logger.log(session_id, chat_model, "final_answer", {"content": REFUSAL_MESSAGE})
                session_manager.add_agent_loop(session_id, prompt, REFUSAL_MESSAGE)
                return

            evidence_block = self._build_evidence_block(prompt, evidence, catalog)
            messages = [{"role": "system", "content": SYNTHESIS_PROMPT}] + history + [
                {"role": "user", "content": evidence_block}]
            async for event in self._finish(chat_model, messages, session_id, prompt):
                yield event

        except Exception as e:
            logger.error(f"Agent pipeline failed: {e}")
            audit_logger.log(session_id, chat_model, "error", {"message": str(e)})
            yield _event("error", message=str(e))

    async def _structured_query(self, prompt: str, route, job_name: str, session_id: str,
                                chat_model: str, history: list, evidence: list) -> AsyncGenerator[str, None]:
        """Forced describe -> SQL generation -> execute with grounded retry.

        Appends successful query results to evidence; appends a fallback marker
        when no schema could be described (caller then runs the ReAct loop).
        """
        describes = []
        for tablename in route.tables:
            events, result = self._run_tool("describeArtifact", {"tablename": tablename},
                                            job_name, session_id, chat_model, "schema_link")
            for event in events:
                yield event
            if result.get("success"):
                describes.append(result)

        if not describes:
            audit_logger.log(session_id, chat_model, "route",
                             {"route": "exploratory", "fallback_reason": "schema_link_failed"})
            evidence.append({"fallback": True, "tables": [], "label": "", "data": None})
            return

        feedback = None
        zero_retry_used = False
        for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
            sql = await pipeline.generate_sql(chat_model, prompt, describes, history, feedback)
            if sql is None:
                audit_logger.log(session_id, chat_model, "sql_attempt",
                                 {"attempt": attempt, "sql": None, "success": False,
                                  "error": "unparseable generation output"})
                feedback = 'Your previous output was not valid JSON of the form {"sql": "..."}. Return only that JSON.'
                continue

            events, result = self._run_tool("queryArtifacts", {"sql": sql},
                                            job_name, session_id, chat_model, "sql")
            for event in events:
                yield event

            if not result.get("success"):
                error = result.get("error", "query failed")
                audit_logger.log(session_id, chat_model, "sql_attempt",
                                 {"attempt": attempt, "sql": sql, "success": False, "error": error})
                feedback = f"Your query failed with this error:\n{error}"
                continue

            row_count = result.get("row_count", 0)
            audit_logger.log(session_id, chat_model, "sql_attempt",
                             {"attempt": attempt, "sql": sql, "success": True,
                              "row_count": row_count})
            if row_count == 0 and not zero_retry_used:
                zero_retry_used = True
                feedback = ZERO_ROWS_HINT
                continue

            # A 0-row result after the retry is valid evidence: "no matching records"
            evidence.append({"label": f"Executed SQL: {sql}",
                             "data": self._cap_query_result(result),
                             "tables": [d.get("tablename") for d in describes]})
            return

    async def _finish(self, chat_model: str, messages: list, session_id: str,
                      prompt: str) -> AsyncGenerator[str, None]:
        """Stream the final answer, audit it, and store the loop in the session"""
        final_answer = ""
        async for chunk in ollama_client.chat_stream(chat_model, messages):
            if chunk.thinking:
                yield _event("thinking", content=chunk.thinking)
            if chunk.content:
                final_answer += chunk.content
                yield _event("token", content=chunk.content)
        yield _event("final", content=final_answer)
        audit_logger.log(session_id, chat_model, "final_answer", {"content": final_answer})
        if final_answer:
            session_manager.add_agent_loop(session_id, prompt, final_answer)

    async def _react_loop(self, prompt: str, session_id: str, job_name: str, chat_model: str,
                          catalog_text: str, history: list) -> AsyncGenerator[str, None]:
        """Bounded ReAct fallback for exploratory questions"""
        system = (f"{REACT_SYSTEM_PROMPT}\n\nThe loaded report is '{job_name}'.\n\n"
                  f"ARTIFACT CATALOG:\n{catalog_text}")
        messages = [{"role": "system", "content": system}] + history + [
            {"role": "user", "content": prompt}]
        tools = get_ollama_tools()
        seen_calls = set()

        final_answer = ""
        for iteration in range(1, REACT_MAX_ITERATIONS + 1):
            content = ""
            tool_calls = []

            async for chunk in ollama_client.chat_stream(chat_model, messages, tools):
                if chunk.thinking:
                    yield _event("thinking", content=chunk.thinking)
                if chunk.content:
                    content += chunk.content
                    yield _event("token", content=chunk.content)
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)

            if not tool_calls:
                final_answer = content
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                # Ollama normally pre-parses arguments to a dict; guard against strings
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                call_key = (name, json.dumps(arguments, sort_keys=True, default=str))
                if call_key in seen_calls:
                    result = {"success": False,
                              "error": "repeated_call: identical tool call already made - use the earlier result or answer now"}
                    yield _event("tool_call", name=name, arguments=arguments)
                    yield _event("tool_result", name=name, success=False,
                                 summary=json.dumps(result))
                else:
                    seen_calls.add(call_key)
                    events, result = self._run_tool(name, arguments, job_name, session_id,
                                                    chat_model, iteration)
                    for event in events:
                        yield event
                # Tool results feed back to the model as role:"tool" messages
                messages.append({"role": "tool", "tool_name": name,
                                 "content": json.dumps(result, default=str)})
        else:
            final_answer = MAX_ITERATIONS_MESSAGE

        yield _event("final", content=final_answer)
        audit_logger.log(session_id, chat_model, "final_answer", {"content": final_answer})
        if final_answer:
            session_manager.add_agent_loop(session_id, prompt, final_answer)


# Global instance
agent_service = AgentService()
