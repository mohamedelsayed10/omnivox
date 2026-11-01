"""LiveKit join tokens."""

from fastapi import APIRouter

from src.api.deps import LiveKitDep
from src.api.schemas.requests import TokenRequest
from src.api.schemas.responses import ErrorResponse, TokenResponse

router = APIRouter(prefix="/livekit", tags=["livekit"])


@router.post(
    "/token",
    response_model=TokenResponse,
    status_code=200,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def create_token(body: TokenRequest, service: LiveKitDep) -> TokenResponse:
    """Issue a join token. Joining a new room makes LiveKit dispatch the voice agent."""
    joined = service.create_token(body.identity, body.room)
    return TokenResponse(
        token=joined.token, url=joined.url, room=joined.room, identity=joined.identity
    )
