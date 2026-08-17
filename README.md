# LinkPlease

Automates Instagram creator DMs. When a user comments a configured keyword on a post, the system sends them a DM via PseudoGram. It guarantees **at-most-one logical delivery** per rule/user pair, protected against external duplication via a stable `Idempotency-Key`, even under retries, crashes, and concurrent workers.

---

## Quick Start

### 1. Get a PseudoGram API key
```bash
curl -X POST https://pseudogram-api.onrender.com/v1/keygen \
  -H "Content-Type: application/json" \
  -d '{"email": "your@email.com"}'
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and set PSEUDOGRAM_API_KEY and WEBHOOK_SECRET to your key
```

### 3. Start the stack
```bash
docker-compose up --build
```

### 4. Create a rule
```bash
curl -X POST http://localhost:8000/rules \
  -H "Content-Type: application/json" \
  -d '{"keyword": "PRICE", "dm_message": "Here is the price list!"}'
```

### 5. Expose publicly and run simulation
```bash
# Install ngrok and run:
ngrok http 8000

# Then trigger the simulation:
curl -X POST https://pseudogram-api.onrender.com/v1/simulate/start \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "https://YOUR_NGROK_URL/webhook", "count": 500, "duration_seconds": 10}'
```

### 6. Check stats
```bash
curl http://localhost:8000/stats
```

---

## Architecture

```
PseudoGram Simulator
      │
      │ POST /webhook (< 10ms response)
      ▼
┌─────────────────┐    INSERT (ON CONFLICT DO NOTHING)    ┌──────────────┐
│  FastAPI App    │ ──────────────────────────────────────► │  PostgreSQL  │
│  (webhook.py)   │                                        │              │
└────────┬────────┘    LPUSH delivery_q                   └──────────────┘
         │ ──────────────────────────────────────────────►
         │                                                ┌──────────────┐
         │                                                │    Redis     │
         │                                                │  (queue +    │
         │                                                │ rate limiter)│
         │                                                └──────┬───────┘
         │                                                       │ BRPOP
         │                                                ┌──────▼───────┐
         │                                                │   delivery   │
         │                                                │   worker     │
         │                                                └──────┬───────┘
         │                                                       │ POST /v1/dm/send
         │                                                ┌──────▼───────┐
         │                                                │  PseudoGram  │
         │                                                │     API      │
         │                                                └──────────────┘
         │
         │  Every 60s                                     ┌──────────────┐
         └───────────────────────────────────────────────► reconciliation│
                                                          │   worker     │
                                                          │ (GET /dm/id) │
                                                          └──────────────┘
```

---

## API Endpoints

### `POST /webhook`
Receives PseudoGram comment events.

**Headers:**
- `X-PseudoGram-Signature: sha256=<hmac>` — required
- `Content-Type: application/json`

**Response:** `200 {"status": "accepted"|"duplicate"|"deleted"}`

### `POST /rules`
**Request:**
```json
{"keyword": "PRICE", "dm_message": "Here's the price list!"}
```
**Response:** `201`
```json
{"rule_id": "uuid", "keyword": "price", "dm_message": "Here's the price list!"}
```

### `GET /stats`
**Response:** `200`
```json
{"sent": 142, "failed": 3, "queued": 8, "duplicates_blocked": 57}
```

### `GET /health`
**Response:** `200 {"status": "ok", "database": "ok"}` or `503` if DB is down.

---

## Database Schema

### `rules`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| keyword | TEXT | stored lowercase |
| dm_message | TEXT | |
| created_at | TIMESTAMPTZ | |

### `webhook_events`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| event_id | TEXT | from PseudoGram |
| event_type | TEXT | comment.created / comment.deleted |
| comment_id | TEXT | |
| post_id | TEXT | |
| user_id | TEXT | identity — never username |
| comment_text | TEXT | |
| raw_payload | JSONB | |
| is_duplicate | BOOLEAN | |
| received_at | TIMESTAMPTZ | |

**Unique:** `(event_id, event_type)`

### `dm_attempts`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | also used as Idempotency-Key |
| rule_id | UUID FK | |
| recipient_user_id | TEXT | |
| comment_id | TEXT | |
| external_dm_id | TEXT | from PseudoGram on success |
| status | TEXT | queued/sending/sent/failed |
| attempt_count | INT | |
| last_error | TEXT | |
| next_retry_at | TIMESTAMPTZ | for 429 backoff |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Unique:** `(rule_id, recipient_user_id)` — THE business idempotency constraint

---

## Failure / Retry Matrix

| Failure | Detection | Recovery | Idempotent? |
|---|---|---|---|
| Duplicate event_id | DB unique constraint | Return 200, count | ✅ |
| Crash after DB write, before Redis push | Startup scan (queued status) | Re-enqueue | ✅ |
| Crash after Redis push, before API call | `sending` status timeout | Re-enqueue | ✅ |
| PseudoGram 500 | HTTP status | Retry up to 5x with backoff | ✅ (idempotency key) |
| PseudoGram 429 | HTTP status + Retry-After | Sleep then retry | ✅ |
| PseudoGram 400 | HTTP status | Mark failed, no retry | N/A |
| Network timeout | httpx.TimeoutException | Retry same as 500 | ✅ (idempotency key) |
| DM accepted but later fails | Reconciliation worker | Mark failed in DB | ✅ |
| Duplicate (rule_id, user_id) | DB unique constraint | Skip silently | ✅ |
| Redis down during enqueue | Exception catch → log | Startup scan recovers | ✅ |
| Worker crash mid-send | `sending` status | Retry with same key | ✅ |

---

## Running Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Unit tests (no infrastructure needed)
pytest tests/unit/ -v

# Integration tests (no infrastructure needed — uses mocks)
pytest tests/integration/ -v

# All tests
pytest tests/ -v --ignore=tests/load/

# Load tests (requires live stack + WEBHOOK_URL env var)
WEBHOOK_URL=https://your-url/webhook \
PSEUDOGRAM_API_KEY=your_key \
pytest tests/load/ -v -s
```

---

## Services

| Service | Command | Description |
|---|---|---|
| app | `uvicorn app.main:app` | FastAPI webhook/API server |
| delivery_worker | `python -m app.workers.delivery_worker` | Processes DM delivery queue |
| reconciliation_worker | `python -m app.workers.reconciliation_worker` | Checks DM delivery status |
| db | PostgreSQL 16 | Source of truth |
| redis | Redis 7 | Queue + rate limiter |

---

## Key Reliability Decisions

1. **DB unique constraint on `(rule_id, recipient_user_id)`** — The single most important line. Prevents any duplicate DM regardless of race conditions, retries, or crashes.

2. **`ON CONFLICT DO NOTHING` on `(event_id, event_type)`** — Deduplicates webhook events at DB level, not in Python.

3. **`status='sending'` before API call** — Crash checkpoint. Any crash during delivery is safely recoverable.

4. **`Idempotency-Key = dm_attempt.id`** — Safe API retries. PseudoGram returns the same dm_id if called twice with the same key.

5. **Redis rate limiter with Lua script** — Atomic sliding-window enforcement. Shared across all worker processes. Never exceeds 10 req/60s.

6. **Reconciliation worker** — Catches the ~15% of PseudoGram DMs that are accepted but later fail silently.

7. **Startup scan** — Worker recovers all stuck jobs after any crash without operator intervention.
