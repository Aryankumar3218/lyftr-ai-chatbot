# Lyftr AI — LLM Chatbot with Key Failover and Response Caching

A full-stack AI chatbot built with **React, FastAPI, SQLite, and LiteLLM**.

The application supports multi-turn conversations, per-request token and latency tracking, LiteLLM response caching, automatic API-key failover, simulated provider failures, and SQLite-backed session history.

---

## 1. Live URLs

- **Frontend:** https://frontend-sooty-alpha-1atr6g6esc.vercel.app
- **Backend:** https://lyftr-ai-chatbot-backend.onrender.com
- **Health Check:** https://lyftr-ai-chatbot-backend.onrender.com/health

> Note: The backend is currently deployed on Render's free tier. Free instances may spin down after inactivity, so the first request after a period of inactivity can take longer.

---

## 2. Run locally: with Docker and without

### Run with Docker

Clone the repository and create the environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Update `.env` with at least two real provider API keys:

```env
LLM_API_KEYS=your_first_key,your_second_key
LLM_MODEL=gemini/gemini-3.5-flash-lite
DATABASE_URL=sqlite:////data/app.db
ALLOWED_ORIGINS=http://localhost:3000
ENABLE_FAILURE_SIMULATION=true
DEFAULT_SYSTEM_PROMPT=You are a helpful assistant.
VITE_API_URL=http://localhost:8000
```

Never commit real API keys to Git.

Start the complete stack:

```bash
make up
```

Local URLs:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Health: http://localhost:8000/health

Stop the stack with:

```bash
make down
```

The Docker Compose configuration mounts a named volume at `/data` for the SQLite database.

### Run without Docker

#### Backend

```bash
cd backend
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Set the required environment variables and start FastAPI:

```bash
uvicorn app.main:app --reload --port 8000
```

#### Frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_URL=http://localhost:8000` when running the frontend locally.

---

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key fallback

`LLM_API_KEYS` contains an ordered pool of provider API keys.

For example:

```text
key_1 → key_2 → key_3
```

The actual API keys are never returned to the frontend.

Instead, safe identifiers such as:

```text
key_1
key_2
```

are included in response metadata.

If a provider request fails because of a retryable error such as:

- HTTP 429
- quota/rate-limit errors
- HTTP 500
- HTTP 502
- HTTP 503

the backend automatically attempts the next configured API key.

If every configured key fails, the API returns:

```json
{
  "detail": "all providers unavailable"
}
```

with HTTP status `503`.

Failed requests are not written to session history.

### Response caching

The project uses **LiteLLM's built-in local exact-match cache**.

The effective cache request is based on the model and the full message list sent to the LLM, including:

- system prompt
- previous conversation history
- new user message

A new request returns:

```text
LIVE_INFERENCE
```

An identical eligible request served from LiteLLM's cache returns:

```text
LLM_CACHE
```

For cache hits:

```text
key_id = null
fallback_attempts = 0
```

Token usage stored with the cached response is returned again.

Cache hits are significantly faster than live provider requests.

### SQLite session storage

Conversation history is stored in SQLite.

The primary table is:

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
```

An index on:

```text
(session_id, id)
```

supports efficient ordered session-history retrieval.

With Docker, the database is configured as:

```text
sqlite:////data/app.db
```

and `/data` is backed by the Docker Compose named volume.

### Multi-turn session context

The frontend sends only the latest user message together with the `session_id`.

The backend retrieves previous messages for that session from SQLite and reconstructs the complete conversation before sending it to the LLM.

Different session IDs remain isolated from one another.

---

## 4. Verification: how to see failover, cache hits and per-message token usage

### Health check

Local:

```bash
curl http://localhost:8000/health
```

Deployed:

```bash
curl https://lyftr-ai-chatbot-backend.onrender.com/health
```

Expected response:

```json
{
  "status": "ok",
  "keys_configured": 2,
  "cache_enabled": true
}
```

### Live inference

```bash
curl -X POST https://lyftr-ai-chatbot-backend.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-live-1","message":"Name one planet in our solar system."}'
```

A new request should contain:

```json
{
  "resolution_source": "LIVE_INFERENCE"
}
```

The metadata also contains:

- model
- latency_ms
- input_tokens
- output_tokens
- key_id
- fallback_attempts

### Cache hit

First send a message in a new session:

```bash
curl -X POST https://lyftr-ai-chatbot-backend.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"cache-demo-1","message":"Name one planet in our solar system."}'
```

Then send the identical first message in another new session:

```bash
curl -X POST https://lyftr-ai-chat