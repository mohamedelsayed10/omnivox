"""Text chat with the agent graph: one-shot invoke and an SSE stream."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.api.deps import ChatDep
from src.api.schemas.requests import ChatRequest
from src.api.schemas.responses import ChatResponse, ErrorResponse

router = APIRouter(prefix="/agent", tags=["agent"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    504: {"model": ErrorResponse},
}
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@router.post("/invoke", response_model=ChatResponse, status_code=200, responses=ERROR_RESPONSES)
async def invoke(body: ChatRequest, request: Request, service: ChatDep) -> ChatResponse:
    """Run one user message through the graph and return the final answer."""
    request_id = request.state.request_id
    result = await service.invoke(body.session_id, body.message, request_id)
    return ChatResponse(
        session_id=result.session_id,
        answer=result.answer,
        tools_used=result.tools_used,
        request_id=request_id,
    )


@router.post("/stream", status_code=200, responses=ERROR_RESPONSES)
async def stream(body: ChatRequest, request: Request, service: ChatDep) -> StreamingResponse:
    """Stream node, tool and token events, ending with ``final`` or ``error``."""
    request_id = request.state.request_id
    events = service.stream(body.session_id, body.message, request_id)  # validates before streaming

    async def frames() -> AsyncIterator[str]:
        async for event in events:
            yield event.encode()

    return StreamingResponse(frames(), media_type="text/event-stream", headers=SSE_HEADERS)
