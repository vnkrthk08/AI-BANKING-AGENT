import os, asyncio, time
from dotenv import load_dotenv
from kural.providers.sarvam import SarvamTTSAdapter

load_dotenv()
api_key = os.getenv("SARVAM_API_KEY")
tts = SarvamTTSAdapter(api_key=api_key)

async def test():
    t0 = time.perf_counter()
    first_chunk_t = None
    total_bytes = 0
    async for chunk in tts.stream_realtime("Hello Rahul, this is Subbu calling from Town Bank."):
        if first_chunk_t is None:
            first_chunk_t = time.perf_counter()
        total_bytes += len(chunk)
    t_end = time.perf_counter()
    print(f"TTS First chunk latency: {(first_chunk_t - t0) * 1000:.1f}ms")
    print(f"TTS Total latency: {(t_end - t0) * 1000:.1f}ms")
    print(f"Total audio bytes received: {total_bytes}")

asyncio.run(test())
