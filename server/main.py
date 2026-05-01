import os
import re
import uuid
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException

load_dotenv()

app = FastAPI(title="Kuun Bridge Server")

BRIDGE_SECRET_KEY = os.getenv("BRIDGE_SECRET_KEY", "default-secret-key")
BOT_TRIGGER = os.getenv("BOT_TRIGGER", "kuun").lower()
WA_API_PORT = int(os.getenv("WA_API_PORT", "8101"))

# In-memory queue/state (minimal by design)
tasks_queue = []
results = {}


def verify_token(authorization: Optional[str]):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    token = authorization.split(" ", 1)[1]
    if token != BRIDGE_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/")
async def root():
    return {"status": "online", "service": "kuun-server"}


@app.post("/webhook/message")
async def handle_incoming_message(payload: dict, authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    message_text = (payload.get("text") or "").strip()
    sender = payload.get("sender", "unknown")
    source = payload.get("source", "unknown")

    if not message_text:
        return {"status": "ignored", "reason": "no text"}

    instruction = message_text
    trigger = BOT_TRIGGER

    if instruction.lower().startswith(trigger):
        # Keep direct shortcuts intact: "<trigger> - ..." or "<trigger> g ..."
        if re.search(rf"^{re.escape(trigger)}\s*(-\s+|g\s+)", instruction, re.IGNORECASE):
            instruction = re.sub(rf"^{re.escape(trigger)}\s*", "", instruction, flags=re.IGNORECASE).strip()
        else:
            instruction = re.sub(rf"^{re.escape(trigger)}\s*[-:]?\s*", "", instruction, flags=re.IGNORECASE).strip()

    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "instruction": instruction,
        "sender": sender,
        "pushName": payload.get("pushName", ""),
        "source": source,
        "mode": payload.get("mode", "agent"),
        "status": "pending",
    }
    tasks_queue.append(task)
    return {"status": "queued", "task_id": task_id}


@app.get("/get-task")
async def get_task(authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    if not tasks_queue:
        return None
    task = tasks_queue.pop(0)
    task["status"] = "processing"
    results[task["id"]] = {"sender": task.get("sender"), "source": task.get("source")}
    return task


@app.post("/status-update")
async def status_update(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    task_id = payload.get("id")
    message = payload.get("message")

    meta = results.get(task_id, {})
    sender = meta.get("sender")
    source = meta.get("source")

    if source == "whatsapp" and sender and message:
        try:
            requests.post(
                f"http://localhost:{WA_API_PORT}/send",
                json={"to": sender, "text": message},
                headers={"Authorization": f"Bearer {BRIDGE_SECRET_KEY}"},
                timeout=5,
            )
        except Exception:
            pass

    return {"status": "sent"}


@app.post("/report-result")
async def report_result(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    task_id = payload.get("id")
    output = payload.get("output", "")

    meta = results.get(task_id, {})
    sender = meta.get("sender")
    source = meta.get("source")

    if source == "whatsapp" and sender:
        try:
            requests.post(
                f"http://localhost:{WA_API_PORT}/send",
                json={"to": sender, "text": output},
                headers={"Authorization": f"Bearer {BRIDGE_SECRET_KEY}"},
                timeout=5,
            )
        except Exception:
            pass

    return {"status": "received"}


if __name__ == "__main__":
    import uvicorn

    fastapi_port = int(os.getenv("FASTAPI_PORT", "8100"))
    bind_host = os.getenv("SERVER_BIND_HOST", "127.0.0.1")
    uvicorn.run(app, host=bind_host, port=fastapi_port)
