import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import litellm
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


DEFAULT_SYSTEM_PROMPT = os.getenv(
    "DEFAULT_SYSTEM_PROMPT",
    "You are a helpful assistant."
)

MODEL = os.getenv(
    "LLM_MODEL",
    "gemini/gemini-3.5-flash-lite"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:////data/app.db"
)

ENABLE_FAILURE_SIMULATION = (
    os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
)

API_KEYS = [
    key.strip()
    for key in os.getenv("LLM_API_KEYS", "").split(",")
    if key.strip()
]

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000"
    ).split(",")
    if origin.strip()
]


# ---------------------------------------------------------
# FastAPI
# ---------------------------------------------------------

app = FastAPI(title="Lyftr AI Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# LiteLLM built-in cache
# ---------------------------------------------------------

litellm.cache = litellm.Cache(type="local")


# ---------------------------------------------------------
# Database
# ---------------------------------------------------------

def db_path() -> str:
    prefix = "sqlite:///"

    if not DATABASE_URL.startswith(prefix):
        raise RuntimeError(
            "DATABASE_URL must be a sqlite:/// URL"
        )

    return DATABASE_URL[len(prefix):]


@contextmanager
def db():
    path = db_path()

    Path(path).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id)
            """
        )


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str = Field(
        min_length=1,
        max_length=128
    )

    message: str = Field(
        min_length=1,
        max_length=4000
    )

    system_prompt: Optional[str] = None

    @field_validator(
        "session_id",
        "message"
    )
    @classmethod
    def nonblank(cls, value: str):
        value = value.strip()

        if not value:
            raise ValueError("must not be empty")

        return value


# ---------------------------------------------------------
# Failure simulation
# ---------------------------------------------------------

def parse_simulation(
    header: Optional[str]
) -> dict[str, int]:

    if not header or not ENABLE_FAILURE_SIMULATION:
        return {}

    result = {}

    try:
        for part in header.split(","):
            key_id, status = part.strip().split("=", 1)

            status = int(status)

            if status not in (
                429,
                500,
                502,
                503
            ):
                raise ValueError

            if key_id != "*" and not key_id.startswith("key_"):
                raise ValueError

            result[key_id] = status

    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="invalid X-Simulate-Failure header"
        )

    return result


# ---------------------------------------------------------
# History
# ---------------------------------------------------------

def history_for(session_id: str):

    with db() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id=?
            ORDER BY id
            """,
            (session_id,)
        ).fetchall()

    return [
        {
            "role": row["role"],
            "content": row["content"]
        }
        for row in rows
    ]


def save_message(
    session_id: str,
    role: str,
    content: str,
    metadata=None
):

    from datetime import datetime, timezone

    with db() as conn:
        conn.execute(
            """
            INSERT INTO messages (
                session_id,
                role,
                content,
                metadata,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                json.dumps(metadata)
                if metadata is not None
                else None,
                datetime.now(
                    timezone.utc
                ).isoformat()
            )
        )


# ---------------------------------------------------------
# Retry handling
# ---------------------------------------------------------

def is_retryable(exc: Exception) -> bool:

    status = getattr(
        exc,
        "status_code",
        None
    )

    name = (
        exc.__class__.__name__
        .lower()
    )

    text = str(exc).lower()

    return (
        status in (
            429,
            500,
            502,
            503
        )
        or "ratelimit" in name
        or "rate limit" in text
        or "quota" in text
        or "serviceunavailable" in name
    )


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health():

    try:
        with db() as conn:
            conn.execute(
                "SELECT 1"
            ).fetchone()

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="database unavailable"
        )

    return {
        "status": "ok",
        "keys_configured": len(API_KEYS),
        "cache_enabled": litellm.cache is not None
    }


# ---------------------------------------------------------
# Chat
# ---------------------------------------------------------

@app.post("/chat")
def chat(
    req: ChatRequest,
    x_simulate_failure: Optional[str] = Header(
        default=None,
        alias="X-Simulate-Failure"
    )
):

    if len(API_KEYS) < 2:
        raise HTTPException(
            status_code=503,
            detail="all providers unavailable"
        )

    previous = history_for(
        req.session_id
    )

    messages = [
        {
            "role": "system",
            "content": (
                req.system_prompt
                or DEFAULT_SYSTEM_PROMPT
            )
        },
        *previous,
        {
            "role": "user",
            "content": req.message
        }
    ]

    simulation = parse_simulation(
        x_simulate_failure
    )

    started = time.perf_counter()
    failed = 0

    for idx, api_key in enumerate(
        API_KEYS,
        start=1
    ):

        key_id = f"key_{idx}"

        # Simulated failure for this key.
        if (
            "*" in simulation
            or key_id in simulation
        ):
            failed += 1
            continue

        try:
            response = litellm.completion(
                model=MODEL,
                messages=messages,
                api_key=api_key,
                caching=True,
                max_retries=0
            )

            latency_ms = int(
                (
                    time.perf_counter()
                    - started
                ) * 1000
            )

            hidden = getattr(
                response,
                "_hidden_params",
                {}
            ) or {}

            cache_hit = bool(
                hidden.get("cache_hit")
            )

            usage = getattr(
                response,
                "usage",
                None
            )

            reply = (
                response
                .choices[0]
                .message
                .content
                or ""
            )

            if not reply.strip():
                raise RuntimeError(
                    "empty model response"
                )

            metadata = {
                "resolution_source": (
                    "LLM_CACHE"
                    if cache_hit
                    else "LIVE_INFERENCE"
                ),

                "model": MODEL,

                "latency_ms": max(
                    0,
                    latency_ms
                ),

                "input_tokens": int(
                    getattr(
                        usage,
                        "prompt_tokens",
                        0
                    )
                    or 0
                ),

                "output_tokens": int(
                    getattr(
                        usage,
                        "completion_tokens",
                        0
                    )
                    or 0
                ),

                "key_id": (
                    None
                    if cache_hit
                    else key_id
                ),

                "fallback_attempts": (
                    0
                    if cache_hit
                    else failed
                )
            }

            save_message(
                req.session_id,
                "user",
                req.message
            )

            save_message(
                req.session_id,
                "assistant",
                reply,
                metadata
            )

            return {
                "session_id": req.session_id,
                "reply": reply,
                "metadata": metadata
            }

        except Exception as exc:

            # Keep useful server-side diagnostics,
            # but never expose provider details to client.
            print(
                f"LLM ERROR | "
                f"key={key_id} | "
                f"type={type(exc).__name__} | "
                f"error={exc}",
                flush=True
            )

            if is_retryable(exc):
                failed += 1
                continue

            raise HTTPException(
                status_code=503,
                detail="all providers unavailable"
            )

    raise HTTPException(
        status_code=503,
        detail="all providers unavailable"
    )


# ---------------------------------------------------------
# Session messages
# ---------------------------------------------------------

@app.get(
    "/sessions/{session_id}/messages"
)
def get_messages(session_id: str):

    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                role,
                content,
                metadata
            FROM messages
            WHERE session_id=?
            ORDER BY id
            """,
            (session_id,)
        ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="session not found"
        )

    messages = []

    for row in rows:

        item = {
            "role": row["role"],
            "content": row["content"]
        }

        if (
            row["role"] == "assistant"
            and row["metadata"]
        ):
            item["metadata"] = json.loads(
                row["metadata"]
            )

        messages.append(item)

    return {
        "session_id": session_id,
        "messages": messages
    }