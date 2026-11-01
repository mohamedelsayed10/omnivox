"""LiveKit access tokens for browser clients."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from livekit import api

from config.settings import Settings

IDENTITY_PREFIX = "user-"
ROOM_PREFIX = "omnivox-"
ID_LENGTH = 8


@dataclass(frozen=True)
class JoinToken:
    """Everything the browser needs to join a room."""

    token: str
    url: str
    room: str
    identity: str


class LiveKitService:
    """Issues short-lived join tokens. A new room name makes LiveKit dispatch the voice agent."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_token(self, identity: str | None = None, room: str | None = None) -> JoinToken:
        """Sign a token for ``identity`` to join ``room`` (both generated when omitted)."""
        settings = self._settings
        identity = identity or f"{IDENTITY_PREFIX}{uuid.uuid4().hex[:ID_LENGTH]}"
        room = room or f"{ROOM_PREFIX}{uuid.uuid4().hex[:ID_LENGTH]}"
        token = (
            api.AccessToken(
                settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET.get_secret_value()
            )
            .with_identity(identity)
            .with_name(identity)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .with_ttl(timedelta(seconds=settings.LIVEKIT_TOKEN_TTL_SECONDS))
            .to_jwt()
        )
        return JoinToken(token=token, url=settings.LIVEKIT_PUBLIC_URL, room=room, identity=identity)
