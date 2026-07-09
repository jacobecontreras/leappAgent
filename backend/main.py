import time
import threading
import json
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from services.agent_service import agent_service
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from database.database import init_database, insert_report_metadata
from utils.processing_utils import validate_leapp_directory, process_leapp_report
from services.settings_service import settings_service
from services.chroma_service import chroma_service
from database.database import init_database, insert_report_metadata, reset_database

load_dotenv()
app = FastAPI()

init_database()

class UploadRequest(BaseModel):
    directory_path: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    job_name: Optional[str] = None

class SettingsRequest(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    rules: Optional[list] = None
    disable_embedding: Optional[bool] = None

@app.post("/upload")
async def upload_report(request: UploadRequest):
    if not validate_leapp_directory(request.directory_path):
        raise HTTPException(status_code=400, detail="Invalid LEAPP report directory: No TSV or Timeline directory found")

    job_name = f"report_{int(time.time())}"
    insert_report_metadata(job_name, request.directory_path)

    # Start background processing
    threading.Thread(target=process_leapp_report, args=(job_name, request.directory_path)).start()
    return {"success": True, "job_name": job_name}


@app.post("/chat")
async def chat_with_ai(request: ChatRequest):
    """Chat with AI assistant for forensic analysis - real-time streaming"""
    async def stream_response():
        try:
            async for response_chunk in agent_service.process_agent_message(request.message, request.session_id, request.job_name):
                # Pass through the structured JSON from agent service
                yield f"data: {response_chunk}\n\n"

            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            # Send error message
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*"
        }
    )


@app.get("/settings")
async def get_settings():
    """Get all AI settings"""
    try:
        settings = settings_service.get_all_settings()
        return {"success": True, "settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@app.put("/settings")
async def update_settings(request: SettingsRequest):
    """Update AI settings"""
    try:
        # Convert request to dict and filter out None values
        settings_to_update = {k: v for k, v in request.dict().items() if v is not None}

        if not settings_to_update:
            raise HTTPException(status_code=400, detail="No settings provided to update")

        success = settings_service.update_settings(settings_to_update)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to update settings")

        # Refresh AI service with new settings
        from services.ai_service import get_ai_service
        ai_service = get_ai_service()
        ai_service.refresh_settings()

        return {"success": True, "message": "Settings updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


@app.post("/settings/clear-data")
async def clear_data():
    """Clear all report data and embeddings"""
    try:
        reset_database()
        chroma_service.reset_collection()
        return {"success": True, "message": "All data cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear data: {str(e)}")


@app.get("/")
async def root():
    return {"message": "LEAPP Forensic Agent API"}
