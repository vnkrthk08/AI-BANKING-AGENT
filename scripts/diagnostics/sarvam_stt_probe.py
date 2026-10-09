import os, time
from dotenv import load_dotenv
from kural.providers.sarvam import SarvamSTTAdapter

load_dotenv()
api_key = os.getenv("SARVAM_API_KEY")
stt = SarvamSTTAdapter(api_key=api_key)

# Read sample audio or test
import glob
wavs = glob.glob("frontend/public/samples/*.wav")
print("Found wav samples:", wavs)
if wavs:
    with open(wavs[0], "rb") as f:
        audio = f.read()
    t0 = time.perf_counter()
    res = stt.transcribe(audio, filename="sample.wav", content_type="audio/wav")
    t1 = time.perf_counter()
    print(f"STT Latency: {(t1 - t0)*1000:.1f}ms")
    print("Transcript:", res.text)
