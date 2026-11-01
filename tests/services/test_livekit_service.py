"""LiveKit token issuing."""

import time

import jwt
from livekit import api

from src.services.livekit_service import LiveKitService


def verify(settings, token: str):
    verifier = api.TokenVerifier(
        settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET.get_secret_value()
    )
    return verifier.verify(token)


def test_token_grants_join_publish_and_data_for_one_room(settings):
    joined = LiveKitService(settings).create_token("alice", "room-1")
    claims = verify(settings, joined.token)
    assert (joined.room, joined.identity, joined.url) == (
        "room-1",
        "alice",
        settings.LIVEKIT_PUBLIC_URL,
    )
    assert claims.identity == "alice"
    video = claims.video
    assert video.room_join and video.room == "room-1"
    assert video.can_publish and video.can_subscribe and video.can_publish_data
    assert not video.room_admin


def test_missing_identity_and_room_are_generated_and_unique(settings):
    service = LiveKitService(settings)
    first, second = service.create_token(), service.create_token()
    assert first.identity.startswith("user-") and first.room.startswith("omnivox-")
    assert first.room != second.room and first.identity != second.identity


def test_token_lifetime_follows_settings(make_settings):
    settings = make_settings(LIVEKIT_TOKEN_TTL_SECONDS=120)
    token = LiveKitService(settings).create_token().token
    payload = jwt.decode(
        token, settings.LIVEKIT_API_SECRET.get_secret_value(), algorithms=["HS256"]
    )
    assert 100 <= payload["exp"] - time.time() <= 125
