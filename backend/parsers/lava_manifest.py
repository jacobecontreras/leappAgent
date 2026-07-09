import os
import json
import logging
from typing import Dict, Any

LAVA_DB_NAME = "_lava_artifacts.db"
LAVA_MANIFEST_NAME = "_lava_data.lava"

logger = logging.getLogger(__name__)


def parse_manifest(directory_path: str) -> Dict[str, Any]:
    """Parse a report's _lava_data.lava manifest into an artifact catalog.

    Table and column names in the LAVA format are derived from module code and
    can drift between LEAPP versions, so everything downstream must resolve
    them through this catalog rather than hardcoding names.
    """
    manifest_path = os.path.join(directory_path, LAVA_MANIFEST_NAME)
    with open(manifest_path) as manifest_file:
        manifest = json.load(manifest_file)

    status = manifest.get("processing_status")
    if status != "Complete":
        raise ValueError(f"LAVA manifest reports processing_status '{status}', expected 'Complete'")

    # meta.modules carries per-artifact descriptions keyed by tablename
    descriptions = {}
    for module in manifest.get("meta", {}).get("modules", []):
        for artifact in module.get("artifacts", []):
            if artifact.get("tablename"):
                descriptions[artifact["tablename"]] = artifact.get("description")

    entries = []
    for category, artifacts in manifest.get("artifacts", {}).items():
        for artifact in artifacts:
            entries.append({
                "category": category,
                "name": artifact["name"],
                "tablename": artifact["tablename"],
                "description": descriptions.get(artifact["tablename"]),
                "record_count": artifact.get("record_count", 0),
                "column_map": artifact.get("column_map", {}),
                "object_columns": artifact.get("object_columns", []),
                "source_path": artifact.get("source_path"),
            })

    logger.info(f"Parsed LAVA manifest: {len(entries)} artifacts from {manifest_path}")
    return {
        "leapp_version": manifest.get("parser_info", {}).get("leapp_version"),
        "entries": entries,
    }
