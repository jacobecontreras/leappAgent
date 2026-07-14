from pydantic import BaseModel

from .validation_schemas import TOOL_SCHEMAS

# Tool descriptions sent to the model via the native tools parameter
TOOL_DESCRIPTIONS = {
    "viewReportList": "List all available reports in the database. Takes no parameters.",
    "viewArtifactList": (
        "List a report's artifacts grouped by category, with each artifact's SQL table name "
        "and record count."
    ),
    "describeArtifact": (
        "Describe one artifact table before querying it: columns with human-readable labels and types, "
        "which columns are epoch timestamps, the original evidence source path, and 3 sample rows."
    ),
    "queryArtifacts": (
        "Run a read-only SQL SELECT against the report's artifact database (SQLite). Use for filtering, "
        "counting, aggregating, sorting, joining, and time-range questions. Only a single SELECT (or WITH) "
        "statement is allowed. Results are capped at 200 rows - a 'truncated' flag tells you if more exist. "
        "Timestamp columns are epoch seconds UTC: use datetime(col, 'unixepoch') to render them, and compare "
        "with strftime('%s', '2020-04-12 13:00:00'). Call describeArtifact first to get exact table and "
        "column names."
    ),
    "searchArtifacts": (
        "Search for a text pattern (phone number, email, name, keyword) across every artifact table in the "
        "report at once. Returns matching rows grouped by artifact. Use when you don't know which artifact "
        "contains the value."
    ),
    "semanticSearch": (
        "Search free-text report content (messages, notes, titles) by semantic similarity to a "
        "natural-language query. Use for vague content questions; use queryArtifacts for exact or "
        "structured lookups."
    ),
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
