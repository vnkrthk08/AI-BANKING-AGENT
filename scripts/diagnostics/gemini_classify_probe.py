from kural.providers.gemini import GeminiAdapter
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
adapter = GeminiAdapter(api_key=api_key, model="gemini-3.6-flash")

try:
    proposal = adapter.classify("Yes")
    print("Classify proposal:", proposal)
except Exception as e:
    import traceback
    traceback.print_exc()
