from google import genai
from kural.providers.schemas import IntentProposal
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

try:
    res = client.models.generate_content(
        model="gemini-3.8-flash",
        contents="You are an NLU engine. Return IntentProposal JSON for 'Yes'.",
        config={
            "response_mime_type": "application/json",
            "response_json_schema": IntentProposal.model_json_schema(),
            "temperature": 0,
            "automatic_function_calling": {"disable": True},
        },
    )
    print("Gemini 3.8 Flash response text:", res.text)
    proposal = IntentProposal.model_validate_json(res.text)
    print("Parsed IntentProposal:", proposal)
except Exception as e:
    import traceback
    traceback.print_exc()
