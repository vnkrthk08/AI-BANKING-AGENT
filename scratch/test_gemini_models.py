import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

for m in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash", "gemini-3.6-flash"]:
    try:
        res = client.models.generate_content(model=m, contents="hello")
        print(f"Model {m}: SUCCESS ({res.text[:30]}...)")
    except Exception as e:
        print(f"Model {m}: FAILED ({type(e).__name__}: {e})")
