import logging
from typing import Dict, Any
from pydantic import ValidationError

from .shared_utils import build_error_response
from .semantic_search import semantic_search
from .artifact_list import artifact_list
from .describe_artifact import describe_artifact
from .query_artifacts import query_artifacts
from .search_artifacts import search_artifacts
from .report_list import report_list

logger = logging.getLogger(__name__)

# Direct tool mapping - simple for desktop app
TOOLS = {
    "viewReportList": report_list,
    "viewArtifactList": artifact_list,
    "describeArtifact": describe_artifact,
    "queryArtifacts": query_artifacts,
    "searchArtifacts": search_artifacts,
    "semanticSearch": semantic_search
}

# Simple schema mapping
from .validation_schemas import TOOL_SCHEMAS


def execute_tool(name: str, input_data: dict):
    """Execute tool with simple validation for desktop application."""
    logger.info(f"Executing tool: '{name}'")

    # Check if tool exists
    tool = TOOLS.get(name)
    if not tool:
        return build_error_response("tool_not_found", f"Tool '{name}' not found")

    # Get schema and validate
    schema = TOOL_SCHEMAS.get(name)
    if not schema:
        return build_error_response("validation_error", f"No validation schema found for tool '{name}'")

    try:
        # Validate input
        validated_data = schema(**input_data)
        # Execute tool
        result = tool(validated_data.model_dump())
        return result

    except ValidationError as e:
        error_details = [f"{'.'.join(str(loc) for loc in error['loc'])}: {error['msg']}" for error in e.errors()]
        return build_error_response(
            "validation_error",
            f"Validation failed: {'; '.join(error_details)}",
            validation_details=error_details
        )

    except Exception as e:
        logger.error(f"Tool execution failed: {str(e)}")
        return build_error_response("execution_error", str(e))