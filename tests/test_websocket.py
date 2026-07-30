import json
import os

import pytest

websockets = pytest.importorskip("websockets")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_ws():
    uri = os.getenv("LLMROUTER_WEBSOCKET_URL")
    if not uri:
        pytest.skip("Set LLMROUTER_WEBSOCKET_URL to run the WebSocket integration test")

    try:
        async with websockets.connect(uri) as websocket:
            request = {
                "model": "auto",
                "messages": [
                    {"role": "user", "content": "Tell me a short joke."}
                ],
                "stream": True,
            }
            await websocket.send(json.dumps(request))

            while True:
                response = await websocket.recv()
                if "[DONE]" in response:
                    break
    except OSError as exc:
        pytest.skip(f"WebSocket service is unavailable at {uri}: {exc}")
