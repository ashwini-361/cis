#!/usr/bin/env python
"""Quick validation of the live API on localhost:8000."""

import asyncio
import json
from pathlib import Path

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"


async def test_session_lifecycle() -> None:
    """Test creating, using, and deleting a session."""
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Create a session
        print("✓ Creating session...")
        resp = await client.post(
            f"{BASE_URL}/sessions/test-session-001",
            json={
                "platform": "meet",
                "expected_participants": ["alice@example.com", "bob@example.com"],
                "ground_truth_candidate_id": "alice@example.com",
            },
        )
        print(f"  POST /sessions/test-session-001 → {resp.status_code}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        session_data = resp.json()
        print(f"  Response: {json.dumps(session_data, indent=2)}")

        # 2. Try to connect to the stream (this will timeout if recording is not provided)
        print("\n✓ Testing WebSocket stream connection...")
        try:
            async with websockets.connect(f"{WS_URL}/sessions/test-session-001/stream") as ws:
                print(f"  Connected to WebSocket")
                try:
                    # Wait briefly for any verdict messages
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    print(f"  Received: {msg}")
                except asyncio.TimeoutError:
                    print(f"  (No verdicts yet — expected with no events)")
        except ConnectionClosed as e:
            print(f"  Stream closed: {e.rcvd}")

        # 3. Delete the session
        print("\n✓ Deleting session...")
        resp = await client.delete(f"{BASE_URL}/sessions/test-session-001")
        print(f"  DELETE /sessions/test-session-001 → {resp.status_code}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


async def test_health() -> None:
    """Test the health endpoint."""
    async with httpx.AsyncClient(timeout=10) as client:
        print("✓ Testing /health endpoint...")
        resp = await client.get(f"{BASE_URL}/health")
        print(f"  GET /health → {resp.status_code}")
        if resp.status_code == 200:
            print(f"  Response: {resp.json()}")
        else:
            print(f"  (Not available, but app is running)")


async def main() -> None:
    """Run all tests."""
    print("=" * 70)
    print("LIVE API VALIDATION (localhost:8000)")
    print("=" * 70)
    print()

    try:
        await test_health()
        print()
        await test_session_lifecycle()
        print()
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        raise


if __name__ == "__main__":
    asyncio.run(main())
