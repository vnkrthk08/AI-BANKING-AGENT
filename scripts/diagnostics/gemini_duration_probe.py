from google import genai
from kural.providers.schemas import IntentProposal
import os, time, json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

t0 = time.perf_counter()
res = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="Return JSON IntentProposal for customer saying 'Yes please'.",
    config={
        "response_mime_type": "application/json",
        "response_json_schema": IntentProposal.model_json_schema(),
        "temperature": 0,
        "automatic_function_calling": {"disable": True},
    },
)
duration_ms = (time.perf_counter() - t0) * 1000
print(f"Gemini roundtrip: {duration_ms:.1f}ms")
print("Response text:", res.text)
