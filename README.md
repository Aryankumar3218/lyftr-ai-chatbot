# Lyftr AI — LLM Chatbot with Key Failover and Response Caching

A React + FastAPI + SQLite chatbot built to the assignment contract. It keeps multi-turn state, exposes per-request inference metadata, uses LiteLLM response caching, and falls back across a pool of provider API keys.

## 1. Live URLs

- Frontend: `ADD_DEPLOYED_FRONTEND_URL`
- Backend: `ADD_DEPLOYED_BACKEND_URL`
- Health: `ADD_DEPLOYED_BACKEND_URL/health`

## 2. Run locally: with Docker and without

### Docker

```bash
cp .env.example .env
# Replace LLM_API_KEYS with at least two real keys.
make up
```

Frontend: http://localhost:3000  
Backend: http://localhost:8000

Stop with `make down`.

### Without Docker

Backend:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:////tmp/lyftr.db
export LLM_API_KEYS=key1,key2
export ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

## 3. Design decisions: key fallback, caching, SQLite session storage

- **Key fallback:** `LLM_API_KEYS` is an ordered pool (`key_1`, `key_2`, ...). `/chat` tries the next key after a 429/quota/5xx-style provider failure. Provider keys are never returned to clients; only their safe IDs are returned.
- **Caching:** LiteLLM's built-in disk cache is enabled. The model and full message list determine an exact request. A cache hit returns `LLM_CACHE`, `key_id: null`, and `fallback_attempts: 0`.
- **SQLite:** Messages are persisted in the `messages` table under the path specified by `DATABASE_URL`. Docker mounts `/data` as a named volume, so session history and the disk cache survive container restarts.
- **Session context:** The client sends only the new message. The backend reconstructs the full prompt from SQLite using `session_id`.

## 4. Verification: how to see failover, cache hits and per-message token usage

Health:
```bash
curl http://localhost:8000/health
```

Live inference:
```bash
curl -X POST http://localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-1","message":"What is the capital of France?"}'
```

Cache hit: send the same first message in a fresh session:
```bash
curl -X POST http://localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-2","message":"What is the capital of France?"}'
```
Look for `metadata.resolution_source = LLM_CACHE` and `key_id = null`.

Failover:
```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"failover-1","message":"Say hello in one sentence."}'
```
With two configured keys, expect HTTP 200, `key_id = key_2`, and `fallback_attempts = 1`.

All keys unavailable:
```bash
curl -i -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"fail-all","message":"hello"}'
```
Expect HTTP 503 and `{"detail":"all providers unavailable"}`; the failed request is not stored.

History:
```bash
curl http://localhost:8000/sessions/demo-1/messages
```

The frontend renders `resolution_source`, model, latency, input tokens and output tokens beside each assistant reply.

## 5. Setup Used: your editor and AI tools

- Editor: `ADD_YOUR_EDITOR`
- AI tools: ChatGPT / `EDIT_IF_NEEDED`

## 6. Bonus features (if any): what you added beyond the requirements and why

- Responsive dark UI with clear inference metadata chips.
- Optional per-request system prompt input.
- Index on `(session_id, id)` for efficient ordered history reads.

## API contract

Exactly three endpoints are exposed:
- `GET /health`
- `POST /chat`
- `GET /sessions/{session_id}/messages`

## Tests

```bash
cd backend
pytest -q
```

The included tests verify health, validation, unknown-session behavior, and that simulated all-key failure returns 503 without writing history.

## Deployment notes

Deploy the frontend to Vercel/Netlify/Render and the backend to a container host with persistent disk support. Set `DATABASE_URL=sqlite:////data/app.db`, mount persistent storage at `/data`, set `ALLOWED_ORIGINS` to the public frontend origin, and keep `ENABLE_FAILURE_SIMULATION=true` for assignment verification. Build the frontend with `VITE_API_URL` pointing to the deployed backend.
