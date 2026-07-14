import os
import time
import json
import threading
from typing import Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from logs.logging_config import setup_logging
from services.agent_service import agent_service
from services.settings_service import settings_service
from services.chroma_service import chroma_service
from services.ollama_client import ollama_client, resolve_default_models
from database.database import init_database, insert_report_metadata, reset_database
from utils.processing_utils import validate_leapp_directory, process_leapp_report

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

setup_logging()
app = FastAPI()

init_database()

class UploadRequest(BaseModel):
    directory_path: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    job_name: Optional[str] = None

class SettingsRequest(BaseModel):
    chat_model: Optional[str] = None
    embed_model: Optional[str] = None
    disable_embedding: Optional[bool] = None


@app.get("/api/ready")
async def ready():
    """Cheap liveness check for app startup — does not probe Ollama"""
    return {"ready": True}


@app.get("/api/health")
async def health():
    """Report Ollama reachability and installed models; resolve default models on first run"""
    if not await ollama_client.is_healthy():
        return {
            "ollama": False,
            "models": [],
            "chat_model": settings_service.get_chat_model(),
            "embed_model": settings_service.get_embed_model()
        }

    resolved = await resolve_default_models(ollama_client)
    installed = {m["name"] for m in resolved["models"]}

    chat_model = settings_service.get_chat_model()
    if chat_model not in installed:
        chat_model = resolved["chat_model"] or ""
        if chat_model:
            settings_service.set_chat_model(chat_model)

    embed_model = settings_service.get_embed_model()
    if embed_model not in installed:
        embed_model = resolved["embed_model"] or ""
        if embed_model:
            settings_service.set_embed_model(embed_model)

    return {
        "ollama": True,
        "models": resolved["models"],
        "chat_model": chat_model,
        "embed_model": embed_model
    }


@app.post("/api/upload")
async def upload_report(request: UploadRequest):
    if not validate_leapp_directory(request.directory_path):
        raise HTTPException(status_code=400, detail="Invalid LEAPP report directory: _lava_artifacts.db and _lava_data.lava (or _lava_data.json) not found (requires iLEAPP v2.x or aLEAPP v3.4+ output)")

    job_name = f"report_{int(time.time())}"
    insert_report_metadata(job_name, request.directory_path)

    # Start background processing
    threading.Thread(target=process_leapp_report, args=(job_name, request.directory_path)).start()
    return {"success": True, "job_name": job_name}


@app.post("/api/chat")
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
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@app.get("/api/settings")
async def get_settings():
    """Get all AI settings"""
    try:
        settings = settings_service.get_all_settings()
        return {"success": True, "settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@app.put("/api/settings")
async def update_settings(request: SettingsRequest):
    """Update AI settings"""
    try:
        # Convert request to dict and filter out None values
        settings_to_update = {k: v for k, v in request.model_dump().items() if v is not None}

        if not settings_to_update:
            raise HTTPException(status_code=400, detail="No settings provided to update")

        # An embedding model change invalidates the existing vector store
        new_embed_model = settings_to_update.get("embed_model")
        embed_model_changed = new_embed_model and new_embed_model != settings_service.get_embed_model()

        success = settings_service.update_settings(settings_to_update)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to update settings")

        if embed_model_changed:
            chroma_service.rebuild(new_embed_model)
            return {"success": True, "message": "Settings updated. Embedding model changed: re-upload reports to rebuild the vector store."}

        return {"success": True, "message": "Settings updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


@app.post("/api/settings/clear-data")
async def clear_data():
    """Clear all report data and embeddings"""
    try:
        reset_database()
        chroma_service.reset_collection()
        return {"success": True, "message": "All data cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear data: {str(e)}")


# Mounted last so /api/* routes take precedence
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
