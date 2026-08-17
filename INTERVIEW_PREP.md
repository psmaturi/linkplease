# 20 Likely Technical Interview Questions and Answers

This document prepares you for a system design or backend engineering interview based on the LinkPlease architecture.

### 1. How do you prevent duplicate webhook events from creating duplicate DMs?
**Answer**: We use a composite `UNIQUE(event_id, event_type)` constraint on the `webhook_events` table in PostgreSQL. When we insert the event, we use `ON CONFLICT DO NOTHING`. If a duplicate arrives concurrently, the database guarantees only one insert succeeds. If the insert returns no rows (or throws an IntegrityError in some DB abstractions), we immediately return 200 OK to acknowledge the webhook, but we skip creating a DM attempt. 

### 2. What is the most critical business invariant and how is it enforced?
**Answer**: "A user must never receive the same rule's DM twice." It's enforced by a database constraint: `UNIQUE(rule_id, recipient_user_id)` on the `dm_attempts` table. We do not rely on Redis, Python sets, or application-level locks. The DB is the final authority. Even if 10 workers process the same event concurrently, only one will successfully insert the row.

### 3. Why not just use Redis to deduplicate webhook events?
**Answer**: Redis is an in-memory data store. If Redis restarts or evicts keys, the deduplication history is lost. By using PostgreSQL, the deduplication history is durable and tied directly to our primary transaction. We use Redis strictly for queuing and rate-limiting as ephemeral performance optimizations, never for business-critical truth.

### 4. How does the system handle a crash right after pulling a job from the queue but before sending the API request?
**Answer**: When the delivery worker pulls a job, its state in the database is `queued`. Before doing anything, the worker updates the state to `sending`. If the worker crashes immediately, the job remains stuck in `sending`. When the worker process boots up again, it runs a "startup scan" that queries the DB for any jobs stuck in `sending`, resets them back to `queued`, and re-processes them.

### 5. What if the worker crashes AFTER sending the API request, but BEFORE saving the response?
**Answer**: The startup scan will eventually reset the job from `sending` to `queued` and retry it. When the worker calls the external API again, it sends the exact same `Idempotency-Key` (which is the UUID of the `dm_attempt`). The external API recognizes the key, sees it already processed the DM, and simply returns the original `dm_id` without sending a second DM. We then save the `dm_id` safely.

### 6. Why use the `dm_attempt.id` (a UUID) as the Idempotency-Key instead of generating a new one per retry?
**Answer**: If we generated a new Idempotency-Key on every retry, a timeout from the external API would lead us to retry with a new key. The external API would treat it as a brand new request and send a duplicate DM. By tying the Idempotency-Key to the deterministic database record, we guarantee safe, idempotent retries.

### 7. How exactly do you enforce the 10 requests / 60 seconds rate limit across multiple workers?
**Answer**: We use a sliding-window rate limiter in Redis, implemented via a Lua script. The script atomically drops timestamps older than 60 seconds, counts the remaining elements, and if under 10, adds the current timestamp. Because Lua scripts are executed atomically in Redis, multiple workers can call the script simultaneously without race conditions (like read-modify-write bugs) that would cause us to exceed the limit.

### 8. The external API returns 202 Accepted. Does that mean the DM was sent?
**Answer**: No. 202 just means it was queued by their system. We must not increment our `sent` statistic yet. We save the `dm_id` and the state remains unconfirmed (in our implementation, we transition it to `sent` but our reconciliation worker treats it as pending final verification).

### 9. How do you handle the 15% silent failure rate of the external API?
**Answer**: We have a background Reconciliation Worker. It periodically queries our DB for `dm_attempts` that have a `dm_id` but haven't reached a terminal state. It calls `GET /v1/dm/{dm_id}` on the external API. If the API says it failed, we mark it failed in our DB and apply our retry logic.

### 10. How do you handle HTTP 429 Too Many Requests?
**Answer**: A 429 means we hit a rate limit (though our internal limiter should prevent this). We read the `Retry-After` header from the response. We calculate a future timestamp (`now + Retry-After`), store it as `next_retry_at` in the database, and leave the job `queued`. The worker query explicitly filters out jobs where `next_retry_at > now()`, effectively pausing that specific delivery until the penalty expires.

## 11. What guarantees do you offer for DM delivery?
**Answer**: We offer **at-most-one logical delivery** per rule/user pair. We guarantee we never intentionally send duplicates by using the PostgreSQL uniqueness constraint. For transient external errors, we use an `Idempotency-Key` to safely retry, avoiding duplication during timeouts. We do NOT guarantee "exactly-once" delivery or "zero-loss" because in distributed systems, if the database commits but the app crashes before queueing, or the API receives the message but times out and is never retried due to max attempts, the message can be lost or stalled.

### 12. If `comment.deleted` arrives before `comment.created`, what happens?
**Answer**: When `comment.deleted` arrives, we insert it into `webhook_events`. Later, when `comment.created` arrives, we insert it. During the business logic execution for `created`, we check if a `comment.deleted` event already exists for that `comment_id`. If it does, we abort and do not send a DM.

### 13. What if `comment.deleted` arrives AFTER the external API accepted the DM?
**Answer**: We do nothing. We cannot un-send a DM that the external API has already processed or queued. We record the actual state honestly. 

### 14. How do you verify the webhook signature?
**Answer**: We take the raw request body bytes, compute an HMAC-SHA256 hash using our `WEBHOOK_SECRET`, and compare it to the `X-PseudoGram-Signature` header. 
*Crucially*, we use `hmac.compare_digest()` to compare the strings in constant time to prevent timing attacks. We also do not parse and re-serialize the JSON before hashing, as subtle formatting changes would break the signature.

### 15. How do you decouple webhook ingestion speed from DM sending speed?
**Answer**: The `POST /webhook` handler only does two things: validates the request and inserts the event into the database. Then, it pushes a notification to a Redis queue and immediately returns HTTP 200. This takes milliseconds. The Delivery Worker asynchronously pulls from the Redis queue and handles the slow external API calls at its own rate-limited pace.

### 16. Why do you use Redis `LPUSH`/`BRPOP` instead of just polling the database for `status='queued'` jobs?
**Answer**: Polling the database every second (e.g., `SELECT * FROM dm_attempts WHERE status='queued'`) is highly inefficient and creates unnecessary DB load, especially when the queue is empty. `BRPOP` is a blocking read—it uses 0 CPU and provides instant notification the moment a job is pushed to the queue. 

### 17. How do you ensure your GET /stats endpoint is accurate and not subject to race conditions?
**Answer**: We do not use in-memory Python counters, as they would reset on crash and be inaccurate across multiple workers. We run a fast `COUNT(*) FILTER (...)` SQL query directly against the `dm_attempts` table. The database aggregates the exact truth at that moment.

### 18. How is case-insensitive substring matching implemented for keywords?
**Answer**: When a rule is created, we store the keyword in the database in lowercase. When a comment arrives, we convert the entire comment text to lowercase once. We then loop through our active rules and use Python's `in` operator: `if rule.keyword in comment_text_lower:`. This correctly matches "price" inside "Can I get the price list?"

### 19. Why should you NEVER log the API key or raw headers?
**Answer**: Security. Logs are often aggregated into systems like Datadog, Splunk, or CloudWatch, which many employees have access to. If an API key is logged, it is considered compromised. We explicitly filter or omit sensitive headers and payload fields before passing them to the logger.

### 20. If you had to scale this system to 10,000 requests per second, what would you change?
**Answer**: 
1. The PostgreSQL insert on the critical path might become a bottleneck. We might switch to Kafka or Kinesis for initial ingestion, acknowledging the webhook immediately, and writing to Postgres asynchronously.
2. The rules table would need to be cached in Redis or in memory, rather than querying Postgres on every event.
3. We would need to partition/shard the `dm_attempts` table by `recipient_user_id` to distribute write load.
4. The rate-limiter Lua script on a single Redis node might bottleneck; we would need Redis Cluster with hash tags for the rate limit keys.
