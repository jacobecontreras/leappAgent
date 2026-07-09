from tools.ollama_schemas import get_ollama_tools, to_ollama_tool, TOOL_DESCRIPTIONS
from tools.validation_schemas import TOOL_SCHEMAS, ArtifactDataSchema


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
    tool = to_ollama_tool("viewArtifactData", ArtifactDataSchema)
    required = tool["function"]["parameters"]["required"]
    assert "job_name" in required
    assert "artifact_type_id" in required
    assert "limit" not in required


def test_no_title_keys():
    for tool in get_ollama_tools():
        assert list(_find_titles(tool["function"]["parameters"])) == []


def test_union_becomes_anyof():
    tool = to_ollama_tool("viewArtifactData", ArtifactDataSchema)
    artifact_type_id = tool["function"]["parameters"]["properties"]["artifact_type_id"]
    assert "anyOf" in artifact_type_id
    types = {option.get("type") for option in artifact_type_id["anyOf"]}
    assert "integer" in types
    assert "array" in types
