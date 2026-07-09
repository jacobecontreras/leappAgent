import logging
from pydantic import BaseModel, Field
from typing import Optional

logger = logging.getLogger(__name__)


class ReportListSchema(BaseModel):
    """Schema for viewReportList - accepts no parameters"""
    pass


class ArtifactListSchema(BaseModel):
    """Schema for viewArtifactList"""
    job_name: str = Field(..., min_length=1)
    model_config = {"extra": "forbid"}


class DescribeArtifactSchema(BaseModel):
    """Schema for describeArtifact"""
    job_name: str = Field(..., min_length=1)
    tablename: str = Field(..., min_length=1)
    model_config = {"extra": "forbid"}


class QueryArtifactsSchema(BaseModel):
    """Schema for queryArtifacts"""
    job_name: str = Field(..., min_length=1)
    sql: str = Field(..., min_length=1)
    model_config = {"extra": "forbid"}


class SearchArtifactsSchema(BaseModel):
    """Schema for searchArtifacts"""
    job_name: str = Field(..., min_length=1)
    pattern: str = Field(..., min_length=1)
    case_sensitive: bool = Field(default=False)
    limit: int = Field(default=50, gt=0, le=200)
    model_config = {"extra": "forbid"}


class SemanticSearchSchema(BaseModel):
    """Schema for semanticSearch"""
    query: str = Field(..., min_length=1)
    job_name: Optional[str] = Field(default=None)
    n_results: int = Field(default=10, gt=0)
    model_config = {"extra": "forbid"}


# Simple tool schema mapping
TOOL_SCHEMAS = {
    "viewReportList": ReportListSchema,
    "viewArtifactList": ArtifactListSchema,
    "describeArtifact": DescribeArtifactSchema,
    "queryArtifacts": QueryArtifactsSchema,
    "searchArtifacts": SearchArtifactsSchema,
    "semanticSearch": SemanticSearchSchema,
}
