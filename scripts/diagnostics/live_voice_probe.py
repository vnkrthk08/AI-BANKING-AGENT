import httpx

client = httpx.Client(base_url="http://127.0.0.1:8000")
res = client.post("/api/v1/sessions", json={"customer_ref": "CUST001"}).json()
print("Session:", res)
session_id = res["session_id"]
turn = client.post(f"/api/v1/sessions/{session_id}/messages", json={"text": "Yes"}).json()
print("Turn:", turn)
