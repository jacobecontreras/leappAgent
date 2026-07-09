import json
import logging
from typing import AsyncGenerator

from tools import execute_tool
from tools.ollama_schemas import get_ollama_tools
from services.ollama_client import ollama_client
from services.session_manager import session_manager
from services.system_prompt import SYSTEM_PROMPT
from services.settings_service import settings_service
from logs.audit import audit_logger

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15
TOOL_RESULT_SUMMARY_LIMIT = 2000
MAX_ITERATIONS_MESSAGE = "I've reached the maximum number of steps. Please try a more specific question."


def _event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload})


class AgentService:
    def _setup_messages(self, prompt: str, session_id: str) -> list:
        """Build the message history: system prompt, session context, user prompt"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(session_manager.get_context_for_ai(session_id))
        messages.append({"role": "user", "content": prompt})
        return messages

    def _execute_tool_call(self, call: dict, job_name: str, session_id: str, chat_model: str, iteration: int) -> tuple:
        """Execute one native tool call, audit it, and return (name, result)"""
        function = call.get("function", {})
        name = function.get("name", "")
        arguments = function.get("arguments") or {}

        # Ollama normally pre-parses arguments to a dict; guard against strings
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if job_name and isinstance(arguments, dict) and "job_name" not in arguments:
            arguments["job_name"] = job_name

        audit_logger.log(session_id, chat_model, "tool_call",
                         {"iteration": iteration, "name": name, "arguments": arguments})

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

        return name, result

    async def process_agent_message(self, prompt: str, session_id: str, job_name: str = None) -> AsyncGenerator[str, None]:
        """Run the ReAct loop: stream model output, execute native tool calls, repeat until a final answer"""
        chat_model = settings_service.get_chat_model()
        if not chat_model:
            yield _event("error", message="No chat model configured. Open settings and select an installed Ollama model.")
            return

        messages = self._setup_messages(prompt, session_id)
        tools = get_ollama_tools()
        audit_logger.log(session_id, chat_model, "user_message", {"message": prompt})

        final_answer = ""
        try:
            for iteration in range(1, MAX_ITERATIONS + 1):
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
                    yield _event("tool_call", name=call.get("function", {}).get("name", ""),
                                 arguments=call.get("function", {}).get("arguments") or {})
                    name, result = self._execute_tool_call(call, job_name, session_id, chat_model, iteration)
                    yield _event("tool_result", name=name, success=bool(result.get("success", True)),
                                 summary=json.dumps(result, default=str)[:TOOL_RESULT_SUMMARY_LIMIT])
                    # Tool results feed back to the model as role:"tool" messages
                    messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, default=str)})
            else:
                final_answer = MAX_ITERATIONS_MESSAGE

        except Exception as e:
            logger.error(f"Agent loop failed: {e}")
            audit_logger.log(session_id, chat_model, "error", {"message": str(e)})
            yield _event("error", message=str(e))
            return

        yield _event("final", content=final_answer)
        audit_logger.log(session_id, chat_model, "final_answer", {"content": final_answer})

        if final_answer:
            session_manager.add_agent_loop(session_id, prompt, final_answer)


# Global instance
agent_service = AgentService()
