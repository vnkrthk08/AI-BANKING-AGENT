import asyncio
import base64
from types import SimpleNamespace

import pytest

from kural.providers.sarvam import SarvamTTSAdapter


def audio_message(payload: bytes):
    return SimpleNamespace(type="audio", data=SimpleNamespace(audio=base64.b64encode(payload).decode()))


def final_message():
    return SimpleNamespace(type="event", data=SimpleNamespace(event_type="final"))


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.configuration = None
        self.text = None
        self.recv_started = asyncio.Event()
        self.block_forever = False

    async def configure(self, **kwargs):
        self.configuration = kwargs

    async def convert(self, text):
        self.text = text

    async def flush(self):
        return None

    async def recv(self):
        self.recv_started.set()
        if self.block_forever:
            await asyncio.Event().wait()
        return next(self.messages)


class FakeContext:
    def __init__(self, websocket, *, connect_error=None):
        self.websocket = websocket
        self.connect_error = connect_error
        self.closed = False

    async def __aenter__(self):
        if self.connect_error:
            raise self.connect_error
        return self.websocket

    async def __aexit__(self, *_args):
        self.closed = True


class FakeClient:
    def __init__(self, contexts):
        self.contexts = iter(contexts)
        self.connect_calls = []
        self.text_to_speech_streaming = SimpleNamespace(connect=self.connect)

    def connect(self, **kwargs):
        self.connect_calls.append(kwargs)
        return next(self.contexts)


def run(coro):
    return asyncio.run(coro)


def test_stream_uses_bulbul_v3_configuration_and_yields_chunks() -> None:
    websocket = FakeWebSocket([audio_message(b"one"), audio_message(b"two"), final_message()])
    context = FakeContext(websocket)
    client = FakeClient([context])
    adapter = SarvamTTSAdapter(client=client)

    async def scenario():
        chunks = [chunk async for chunk in adapter.stream("A short response")]
        await adapter.close()
        return chunks

    chunks = run(scenario())

    assert chunks == [b"one", b"two"]
    assert websocket.text == "A short response"
    assert client.connect_calls[0]["model"] == "bulbul:v3"
    assert websocket.configuration["target_language_code"] == "en-IN"
    assert websocket.configuration["output_audio_codec"] == "mp3"
    assert websocket.configuration["min_buffer_size"] == 30
    assert context.closed


def test_realtime_stream_uses_linear16_for_progressive_browser_audio() -> None:
    websocket = FakeWebSocket([audio_message(b"pcm-one"), final_message()])
    context = FakeContext(websocket)
    adapter = SarvamTTSAdapter(client=FakeClient([context]))

    async def scenario():
        chunks = [chunk async for chunk in adapter.stream_realtime("A short response")]
        await adapter.close()
        return chunks

    assert run(scenario()) == [b"pcm-one"]
    assert websocket.configuration["output_audio_codec"] == "linear16"
    assert adapter.realtime_sample_rate == 24000


def test_connection_failure_retries_connect_and_reports_sanitized_error() -> None:
    client = FakeClient([
        FakeContext(None, connect_error=ConnectionError("private endpoint details")),
        FakeContext(None, connect_error=ConnectionError("private endpoint details")),
    ])
    adapter = SarvamTTSAdapter(client=client)

    async def scenario():
        with pytest.raises(RuntimeError, match="WebSocket connection failed") as error:
            _ = [chunk async for chunk in adapter.stream("Hello")]
        assert "private endpoint" not in str(error.value)

    run(scenario())
    assert len(client.connect_calls) == 2


def test_empty_stream_is_reported_as_failure() -> None:
    adapter = SarvamTTSAdapter(client=FakeClient([FakeContext(FakeWebSocket([final_message()]))]))

    async def scenario():
        with pytest.raises(ValueError, match="empty stream"):
            _ = [chunk async for chunk in adapter.stream("Hello")]

    run(scenario())


def test_cancellation_closes_persistent_connection() -> None:
    websocket = FakeWebSocket([])
    websocket.block_forever = True
    context = FakeContext(websocket)
    adapter = SarvamTTSAdapter(client=FakeClient([context]))

    async def scenario():
        async def consume():
            async for _chunk in adapter.stream("Please help"):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(websocket.recv_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert context.closed
