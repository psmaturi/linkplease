import asyncio
import hashlib
import hmac
import json
import time
import httpx
from random import choice

API_BASE = "http://localhost:8000"
SECRET = "test_api_key_12345"

def sign_body(body: bytes) -> str:
    digest = hmac.new(key=SECRET.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"

async def trigger_webhook(client, event_id, text, comment_id):
    body = json.dumps({
        "event_id": event_id,
        "event_type": "comment.created",
        "comment": {
            "comment_id": comment_id,
            "post_id": "post_1",
            "user_id": f"user_{comment_id}",
            "text": text
        }
    }).encode()
    
    headers = {
        "Content-Type": "application/json",
        "X-PseudoGram-Signature": sign_body(body)
    }
    
    start = time.monotonic()
    resp = await client.post(f"{API_BASE}/webhook", content=body, headers=headers)
    latency = time.monotonic() - start
    return resp.status_code, latency

async def run_local_load_test():
    print("Starting local load test (500 events)...")
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Create rules
        await client.post(f"{API_BASE}/rules", json={"keyword": "PRICE", "dm_message": "Price 1"})
        await client.post(f"{API_BASE}/rules", json={"keyword": "LINK", "dm_message": "Link 1"})
        
        # Fire 500 events concurrently
        texts = ["price please", "give me the LINK", "random comment", "PRICE"]
        tasks = []
        for i in range(500):
            # Introduce some duplicates (10%)
            event_id = f"evt_{i}" if i % 10 != 0 else f"evt_{i-1}"
            tasks.append(trigger_webhook(client, event_id, choice(texts), f"cmt_{i}"))
            
        start = time.monotonic()
        results = await asyncio.gather(*tasks)
        duration = time.monotonic() - start
        
        status_codes = [r[0] for r in results]
        latencies = [r[1] for r in results]
        
        print(f"Sent 500 events in {duration:.2f}s")
        print(f"Status codes: 200={status_codes.count(200)}, 500={status_codes.count(500)}")
        print(f"Max latency: {max(latencies):.4f}s, Avg: {sum(latencies)/len(latencies):.4f}s")

if __name__ == "__main__":
    asyncio.run(run_local_load_test())
