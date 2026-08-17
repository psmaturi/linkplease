# Failures and Limitations

This document explicitly catalogs the known reliability boundaries of the LinkPlease system. 

## 1. External System Uncertainty & Infinite Polling Avoidance
PseudoGram operates an unreliable mock API that frequently returns `202 Accepted` but stalls DMs in the `queued` state forever (~15% of the time) or drops them entirely.

**How LinkPlease Handles This:**
- When an API returns `202 Accepted`, we change the local attempt status to `accepted` (this strictly does *not* count as `sent`).
- Our background Reconciliation Worker polls `GET /v1/dm/{dm_id}` using a bounded exponential backoff with jitter (e.g., 10s, 20s, 40s...).
- If the external API accepts a DM but never transitions its status from `queued` to a terminal state (`delivered` or `failed`) after the maximum reconciliation attempts, the system marks the attempt as `unresolved`.

**The Limitation:**
The system cannot magically determine whether the DM was ultimately delivered if the external API never provides a final status. Therefore, the system *does not create a second logical delivery* merely to compensate for an unknown external state. We assume the external queue might eventually process it, and rely on our strict `(rule_id, user_id)` unique constraint to protect the user from being spammed with duplicates.

## 2. Process Crash During External POST
If the worker process crashes precisely between transmitting the `POST /v1/dm/send` payload and receiving the HTTP response, the local state remains `sending`.

**How LinkPlease Handles This:**
- Upon restart, the system finds all `sending` jobs and resets them to `queued` to retry them.
- We supply the `Idempotency-Key` (using the UUID of the `dm_attempt` row) to the external API.

**The Limitation:**
This completely protects against duplicate DMs *only if* the external API correctly implements its idempotency cache. If the external API fails to honor the `Idempotency-Key`, a duplicate DM could technically occur. We cannot guarantee "exactly-once" delivery over a network without the downstream participant perfectly honoring idempotency.

## 3. Ephemeral Redis Transport
Redis is used as a fast, blocking message queue (`LPUSH` / `BRPOP`) and for sliding-window rate limiting. 

**How LinkPlease Handles This:**
- Webhook payloads are durable. The `webhook_events`, `dm_attempts`, and `outbox_events` are committed into PostgreSQL first (Transactional Outbox).
- A background worker (`outbox_publisher.py`) ensures that even if Redis goes down or crashes, all committed events are eventually published to the queue.

**The Limitation:**
Redis data is ephemeral. If Redis crashes and drops its queue, the `outbox_publisher` will recreate the pending work. No jobs are lost. 
