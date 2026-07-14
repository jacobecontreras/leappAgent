import os
import json
import logging
from typing import Dict, Any, Optional

LAVA_DB_NAME = "_lava_artifacts.db"
LAVA_MANIFEST_NAME = "_lava_data.lava"
# Newer ALEAPP exports use .json; older iLEAPP/aLEAPP use .lava (same JSON body)
LAVA_MANIFEST_CANDIDATES = (LAVA_MANIFEST_NAME, "_lava_data.json")

logger = logging.getLogger(__name__)


def find_manifest_path(directory_path: str) -> Optional[str]:
    """Return the path to a LAVA manifest if one exists (.lava preferred over .json)"""
    for name in LAVA_MANIFEST_CANDIDATES:
        path = os.path.join(directory_path, name)
        if os.path.isfile(path):
            return path
    return None


def parse_manifest(directory_path: str) -> Dict[str, Any]:
    """Parse a report's LAVA manifest into an artifact catalog.

    Table and column names in the LAVA format are derived from module code and
    can drift between LEAPP versions, so everything downstream must resolve
    them through this catalog rather than hardcoding names.
    """
    manifest_path = find_manifest_path(directory_path)
    if not manifest_path:
        raise FileNotFoundError(
            f"No LAVA manifest found in {directory_path} "
            f"(expected one of: {', '.join(LAVA_MANIFEST_CANDIDATES)})"
        )

    with open(manifest_path) as manifest_file:
        manifest = json.load(manifest_file)

    status = manifest.get("processing_status")
    if status != "Complete":
        raise ValueError(f"LAVA manifest reports processing_status '{status}', expected 'Complete'")

    # Descriptions: classic .lava puts modules under meta; some .json exports use top-level modules
    modules = manifest.get("meta", {}).get("modules") or manifest.get("modules") or []
    descriptions = {}
    for module in modules:
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
        "manifest_path": manifest_path,
    }
