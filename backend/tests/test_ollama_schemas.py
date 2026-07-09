from tools.ollama_schemas import get_ollama_tools, to_ollama_tool, TOOL_DESCRIPTIONS
from tools.validation_schemas import TOOL_SCHEMAS, QueryArtifactsSchema, SemanticSearchSchema


def _find_titles(node):
    if isinstance(node, dict):
        if "title" in node:
            yield node["title"]
        for value in node.values():
            yield from _find_titles(value)
    elif isinstance(node, list):
        for item in node:
            yield from _find_titles(item)


def test_every_tool_converts():
    tools = get_ollama_tools()
    assert len(tools) == len(TOOL_SCHEMAS)
    names = {t["function"]["name"] for t in tools}
    assert names == set(TOOL_SCHEMAS.keys())


def test_tool_shape_and_description():
    for tool in get_ollama_tools():
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["description"] == TOOL_DESCRIPTIONS[function["name"]]
        assert function["parameters"]["type"] == "object"


def test_required_fields():
    tool = to_ollama_tool("queryArtifacts", QueryArtifactsSchema)
    required = tool["function"]["parameters"]["required"]
    assert "job_name" in required
    assert "sql" in required


def test_no_title_keys():
    for tool in get_ollama_tools():
        assert list(_find_titles(tool["function"]["parameters"])) == []


def test_optional_becomes_anyof():
    tool = to_ollama_tool("semanticSearch", SemanticSearchSchema)
    job_name = tool["function"]["parameters"]["properties"]["job_name"]
    assert "anyOf" in job_name
    types = {option.get("type") for option in job_name["anyOf"]}
    assert "string" in types
    assert "null" in types
