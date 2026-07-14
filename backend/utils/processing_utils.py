import os
import logging
import time
from parsers.lava_manifest import parse_manifest, find_manifest_path, LAVA_DB_NAME
from database.database import update_report_status, store_artifact_catalog, store_ingested_file, set_report_leapp_version
from utils.embedding_utils import embed_job_data
from utils.hash_utils import sha256_file
from services.settings_service import settings_service

logger = logging.getLogger(__name__)


def validate_leapp_directory(directory_path: str) -> bool:
    """Validate that a directory is a LAVA-format LEAPP report"""
    if not os.path.exists(directory_path):
        return False

    db_path = os.path.join(directory_path, LAVA_DB_NAME)
    return os.path.isfile(db_path) and find_manifest_path(directory_path) is not None

def hash_report_files(job_name: str, directory_path: str) -> int:
    """Record a SHA-256 manifest of the LAVA evidence files before any parsing"""
    manifest_path = find_manifest_path(directory_path)
    if not manifest_path:
        raise FileNotFoundError(f"No LAVA manifest found in {directory_path}")

    source_files = [
        os.path.join(directory_path, LAVA_DB_NAME),
        manifest_path,
    ]

    for file_path in source_files:
        store_ingested_file(job_name, file_path, sha256_file(file_path), os.path.getsize(file_path))

    logger.info(f"Hashed {len(source_files)} source files for job: {job_name}")
    return len(source_files)

def process_leapp_report(job_name: str, directory_path: str):
    """Main processing pipeline for LEAPP forensic reports.

    Hashes the LAVA files and stores the artifact catalog from the manifest.
    The artifact data itself stays in the report's _lava_artifacts.db, which
    is only ever opened read-only.
    """
    start_time = time.time()
    logger.info(f"Starting processing for job: {job_name}")

    try:
        update_report_status(job_name, "processing")

        # Hash source evidence files before touching them further
        hash_report_files(job_name, directory_path)

        # Parse the LAVA manifest into the artifact catalog
        logger.info(f"Parsing LAVA manifest for job: {job_name}")
        manifest = parse_manifest(directory_path)
        store_artifact_catalog(job_name, manifest["entries"])
        if manifest["leapp_version"]:
            set_report_leapp_version(job_name, manifest["leapp_version"])

        # Mark as completed and start embedding
        update_report_status(job_name, "completed")

        if not settings_service.get_disable_embedding():
            logger.info(f"Starting embedding for job: {job_name}")
            embed_job_data(job_name)
        else:
            logger.info(f"Skipping embedding for job: {job_name} (disabled in settings)")

        processing_time = time.time() - start_time
        logger.info(f"Completed processing for job: {job_name} in {processing_time:.2f} seconds")

    except Exception as e:
        logger.error(f"Failed to process job {job_name}: {str(e)}")
        update_report_status(job_name, "failed", str(e))
