"""WebSocket verdict stream per docs/ARCHITECTURE.md §1.8."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.session import SessionManager

router = APIRouter()


def make_router(session_manager: SessionManager) -> APIRouter:
    """Return a router bound to the given SessionManager instance."""

    @router.websocket("/sessions/{session_id}/stream")
    async def session_stream(websocket: WebSocket, session_id: str) -> None:
        """Outbound verdict stream for the dashboard.

        Verdicts arrive via SessionManager.broadcast_verdict (called by the
        realtime ticker each tick). This route never reads anything meaningful
        from the client; it just holds the connection open and pushes.
        """
        await websocket.accept()
        session = session_manager.get_session(session_id)
        if session is None:
            await websocket.close(code=4404, reason="unknown session_id")
            return

        payload = session_manager._stream_payload(session_id)
        if payload is not None:
            await websocket.send_json(payload)
        session_manager.add_subscriber(session_id, websocket)

        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            session_manager.remove_subscriber(session_id, websocket)

    return router
