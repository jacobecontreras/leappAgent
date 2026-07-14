import os
import sys
import time
import socket
import threading
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)  # backend paths (logs, database) are relative to backend/

import uvicorn
import webview

from main import app as fastapi_app

WINDOW_TITLE = "LEAPP Agent"
STARTUP_TIMEOUT = 30


class JsApi:
    """Native APIs exposed to the frontend via window.pywebview.api"""

    def select_folder(self):
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return {"success": bool(result), "directory_path": result[0] if result else None}


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_ready(url: str, timeout: int):
    """Poll a cheap liveness URL until the backend accepts connections.

    Do not use /api/health here: that probes Ollama (version/tags/show per model)
    and can take several seconds over a remote tunnel, exceeding a short HTTP
    timeout and blocking the window from ever opening.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Backend did not start within {timeout} seconds")


def main():
    port = find_free_port()
    # uvicorn.Server on a daemon thread: uvicorn.run() would install signal
    # handlers, which fails off the main thread; the webview must own main
    # (Cocoa requirement on macOS)
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}"
    wait_until_ready(f"{url}/api/ready", STARTUP_TIMEOUT)

    webview.create_window(WINDOW_TITLE, url, js_api=JsApi(), width=1200, height=800)
    webview.start()  # blocks until the window is closed

    server.should_exit = True
    server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
