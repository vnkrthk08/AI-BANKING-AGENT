import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace

from kural.providers.sarvam import SarvamRealtimeSTTAdapter


class FakeRealtimeSocket:
    def __init__(self):
        self.audio_messages = []
        self.ended = False

    async def send_realtime_audio_input(self, message):
        self.audio_messages.append(message)

    async def send_realtime_end(self, _message):
        self.ended = True

    async def recv(self):
        return SimpleNamespace(event="session.begin")


class FakeRealtimeResource:
    def __init__(self, socket):
        self.socket = socket
        self.options = None

    @asynccontextmanager
    async def connect(self, **options):
        self.options = options
        yield self.socket


def test_realtime_adapter_uses_official_fast_pcm_vad_contract_and_encodes_audio():
    socket = FakeRealtimeSocket()
    resource = FakeRealtimeResource(socket)
    adapter = SarvamRealtimeSTTAdapter(client=SimpleNamespace(speech_to_text_realtime_streaming=resource))

    async def scenario():
        async with adapter.connect() as session:
            await session.send_audio(b"pcm-frame")
            await session.end()

    asyncio.run(scenario())

    assert resource.options == {
        "language_code": "en-IN", "model": "saaras:v4", "stream_type": "fast",
        "mode": "transcribe", "endpointing": "vad", "encoding": "linear16",
        "sample_rate": "16000", "threshold": "0.3", "prefix_padding_ms": "200",
        "silence_duration_ms": "500", "min_speech_duration_ms": "250",
        "request_options": {"max_retries": 0},
    }
    assert socket.audio_messages[0].audio == base64.b64encode(b"pcm-frame").decode("ascii")
    assert socket.ended
