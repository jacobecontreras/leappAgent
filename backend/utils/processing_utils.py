import os
import logging
import time
from parsers.tsv_parser import parse_tsv_directory
from parsers.leapp_db_parser import parse_timeline_db
from database.database import update_report_status, store_tsv_data, store_timeline_data
from utils.embedding_utils import embed_job_data
from services.settings_service import settings_service

logger = logging.getLogger(__name__)

# Required subdirectories in LEAPP reports
REQUIRED_DIRS = ['_TSV Exports', '_Timeline']


def validate_leapp_directory(directory_path: str) -> bool:
    """Validate LEAPP directory structure by checking required subdirectories"""
    if not os.path.exists(directory_path):
        return False

    return all(
        os.path.exists(os.path.join(directory_path, dir_name))
        for dir_name in REQUIRED_DIRS
    )

def process_leapp_report(job_name: str, directory_path: str):
    """Main processing pipeline for LEAPP forensic reports"""
    start_time = time.time()
    logger.info(f"Starting processing for job: {job_name}")

    try:
        update_report_status(job_name, "processing")

        # Process TSV exports and store data in SQLite
        logger.info(f"Processing TSV files for job: {job_name}")
        tsv_path = os.path.join(directory_path, '_TSV Exports')
        tsv_data = parse_tsv_directory(tsv_path)
        store_tsv_data(job_name, tsv_data)

        # Process timeline data and store data and store data in SQLite
        logger.info(f"Processing timeline data for job: {job_name}")
        timeline_path = os.path.join(directory_path, '_Timeline', 'tl.db')
        timeline_data = parse_timeline_db(timeline_path)
        store_timeline_data(job_name, timeline_data)

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