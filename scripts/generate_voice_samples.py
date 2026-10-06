import os
import json
import urllib.request
import base64
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("SARVAM_API_KEY")

out_dir = Path("frontend/public/samples")
out_dir.mkdir(parents=True, exist_ok=True)

url = "https://api.sarvam.ai/text-to-speech"
headers = {
    "api-subscription-key": api_key,
    "Content-Type": "application/json"
}

samples = [
    (
        out_dir / "voice_subbu_male.wav",
        "aditya",
        "Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with Rahul? I'm calling about a quick update to your Town Bank mobile app — is now a good time for two minutes?"
    ),
    (
        out_dir / "voice_priya_female.wav",
        "priya",
        "Hello Rahul, this is Town Bank customer support. We are checking in to make sure your Town Bank mobile app is up to date and working smoothly."
    )
]

for out_path, speaker, text in samples:
    try:
        payload = json.dumps({
            "inputs": [text],
            "target_language_code": "en-IN",
            "speaker": speaker,
            "pitch": 0,
            "pace": 1.0,
            "loudness": 1.0,
            "speech_sample_rate": 22050,
            "enable_preprocessing": True,
            "model": "bulbul:v3"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            audios = res_json.get("audios", [])
            if audios:
                wav_bytes = base64.b64decode(audios[0])
                with open(out_path, "wb") as f:
                    f.write(wav_bytes)
                print(f"[SUCCESS] Synthesized {speaker} -> {out_path} ({len(wav_bytes)} bytes)")
            else:
                print(f"[FAIL] No audios for {speaker}: {res_json}")
    except urllib.error.HTTPError as e:
        print(f"[HTTP ERROR] Synthesizing {speaker}: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"[ERROR] Synthesizing {speaker}: {e}")
