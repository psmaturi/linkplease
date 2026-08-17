# Reliability & Failure Recovery

This document explains the reliability mechanisms, idempotency strategies, and crash recovery behaviors of the LinkPlease system.

## Core Invariant: One Rule + One User = At Most One Delivery
The primary business invariant is guaranteed entirely by PostgreSQL:
```sql
ALTER TABLE dm_attempts ADD CONSTRAINT uq_rule_user UNIQUE (rule_id, recipient_user_id);
```
No matter what happens in the application layer—network partitions, worker crashes, duplicate events, concurrent webhook requests—it is mathematically impossible for the system to create two DM delivery attempts for the same user on the same rule.

## Processing Guarantees
- **Webhook Ingestion**: We process webhooks internally with *at-least-once* guarantees, utilizing DB `ON CONFLICT DO NOTHING` for idempotent handling.
- **DM Delivery**: We guarantee *at-most-one* logical delivery per rule/user pair internally, and we leverage the external API's `Idempotency-Key` to safely retry requests without duplication. Final delivery is only considered successful upon confirmed `delivered` status.

## Failure Windows & Crash Recovery

### A. Crash before webhook persistence
If the app crashes before the `INSERT` completes, no response is sent to PseudoGram. PseudoGram will retry the webhook later. Safe.

### B. Crash after webhook persistence but before queueing
If the DB commit succeeds but the app crashes before pushing to Redis, the job isn't in the queue. 
**Recovery**: The worker's startup scan explicitly queries the DB for `status='queued'` jobs and processes them, effectively bypassing the need for the Redis push. Safe.

### C. Crash after queueing but before worker claims
The job sits in Redis. Once the worker restarts, it will pull the job from Redis via `BRPOP`. Safe.

### D. Crash after Delivery creation but before sending (Worker Crash)
The worker sets `status='sending'` in the DB before making the API call. If the worker crashes immediately, the row remains stuck in `sending`.
**Recovery**: Upon worker restart, a startup scan looks for `status='sending'` rows, resets them to `queued`, and re-processes them. Safe.

### E. Crash while sending
Same as above (D).

### F. External API accepts the request but application times out
The external API has processed the DM, but we threw an `httpx.TimeoutException`. The worker will catch the error, leave the state in `queued`, and retry later.
**Safety**: Because we pass `Idempotency-Key: <dm_attempt.id>`, PseudoGram recognizes the duplicate request on retry and simply returns the original `dm_id` without sending a second DM. Safe.

### G. External API accepts request but application crashes before saving dm_id
Same as (F). On restart, the startup scan resets `sending` to `queued`. The worker retries the API call. The `Idempotency-Key` prevents a double-send. PseudoGram returns the original `dm_id`, which we then save. Safe.

### H. Worker crashes during retry
Recovered automatically by the startup scan on the next boot. Safe.

### I. Two workers claim the same delivery
Impossible by design. The Redis `BRPOP` is atomic—only one worker gets the queue item. If both were somehow manually triggered, the database UPDATE to set `status='sending'` uses row-level locking or optimistic checks (we query first), preventing concurrent execution.

### J. Duplicate webhook requests arrive concurrently
They both attempt to `INSERT` the event. PostgreSQL's `UNIQUE` constraint forces one to fail with an `IntegrityError`. We catch it, treat it as a duplicate, and return 200. Only one transaction proceeds to create the `dm_attempt`. Safe.

## Rate Limiting
PseudoGram strictly enforces 10 requests / 60 seconds.
- We use a Redis sorted set (`ZADD` / `ZREMRANGEBYSCORE` / `ZCARD`).
- The logic is wrapped in a Lua script.
- Lua scripts run atomically in Redis.
- This means multiple concurrent workers can safely request rate-limit tokens without race conditions that could lead to exceeding the 10 req/min limit.

## Retry Policy
- **HTTP 400**: Permanent Failure. Marked as `failed`. Never retried.
- **HTTP 500 / Network Timeout**: Retryable Failure. We use exponential backoff with a cap. Max attempts: 5.
- **HTTP 429**: Rate Limited. We parse the `Retry-After` header, calculate the exact `next_retry_at` timestamp, save it to the DB, and pause processing that attempt until the time has passed.

## Consistency Guarantees
- The DB is the absolute source of truth.
- Redis is an ephemeral performance optimization for queuing and rate-limiting.
- If Redis is wiped, no data is lost. The startup scan recovers all pending jobs directly from Postgres.
- Accurate statistics (`/stats`) are calculated via DB `COUNT(*)` queries on the fly, not by fragile incrementing counters.
