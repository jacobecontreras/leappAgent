from pydantic import BaseModel

from .validation_schemas import TOOL_SCHEMAS

# Tool descriptions sent to the model via the native tools parameter
TOOL_DESCRIPTIONS = {
    "viewReportList": "List all available reports in the database. Takes no parameters.",
    "viewArtifactList": "List all artifact types for a specific report.",
    "viewArtifactData": (
        "View data rows from one or more artifact types. artifact_type_id accepts a single ID or a list of IDs. "
        "Maximum 200 results per call; for large datasets paginate with offset=0, 200, 400, etc."
    ),
    "grepSearch": "Search report data for a text pattern, optionally scoped to specific artifact types.",
    "semanticSearch": "Search report data by semantic similarity to a natural-language query.",
}


def _strip_titles(schema: dict):
    """Recursively remove pydantic's auto-generated 'title' keys"""
    if isinstance(schema, dict):
        schema.pop("title", None)
        for value in schema.values():
            _strip_titles(value)
    elif isinstance(schema, list):
        for item in schema:
            _strip_titles(item)


def to_ollama_tool(name: str, schema_cls: type[BaseModel]) -> dict:
    """Convert a pydantic tool schema into Ollama's tool definition format"""
    parameters = schema_cls.model_json_schema()
    _strip_titles(parameters)
    parameters.pop("description", None)  # class docstring; the tool description covers it
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": parameters
        }
    }


def get_ollama_tools() -> list[dict]:
    """All agent tools in Ollama tool definition format"""
    return [to_ollama_tool(name, schema_cls) for name, schema_cls in TOOL_SCHEMAS.items()]
