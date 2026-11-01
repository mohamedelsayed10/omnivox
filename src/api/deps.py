"""Composition root of the API: builds the services once and injects them via ``Depends``."""

import secrets
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from config.settings import Settings
from src.ai_models.asr import SpeechToText
from src.ai_models.base import ModelInfo
from src.ai_models.tts import TextToSpeech
from src.ai_models.turn import TurnDetection
from src.composition import Runtime, build_runtime
from src.graph.memory import open_checkpointer
from src.services.chat_service import ChatService
from src.services.knowledge_service import KnowledgeService
from src.services.livekit_service import LiveKitService
from src.utils.exceptions import UnauthorizedError


@dataclass
class Container:
    """Everything the routes need, created at startup."""

    settings: Settings
    runtime: Runtime
    chat: ChatService
    knowledge: KnowledgeService
    livekit: LiveKitService

    def model_infos(self) -> list[ModelInfo]:
        """Configured models, for the info endpoint."""
        return [
            self.runtime.llm.info,
            self.runtime.embeddings.info,
            SpeechToText(self.settings).info,
            TextToSpeech(self.settings).info,
            TurnDetection(self.settings).info,
        ]


async def build_container(settings: Settings, stack: AsyncExitStack) -> Container:
    """Create the runtime, open the checkpointer and wire the services. Closed by ``stack``."""
    runtime = build_runtime(settings)
    stack.push_async_callback(runtime.aclose)
    checkpointer = await stack.enter_async_context(open_checkpointer(settings))
    graph = runtime.build_graph(checkpointer)
    return Container(
        settings=settings,
        runtime=runtime,
        chat=ChatService(graph, settings, runtime.tracing),
        knowledge=KnowledgeService(runtime.retriever, settings),
        livekit=LiveKitService(settings),
    )


def get_container(request: Request) -> Container:
    """The container created in the app lifespan."""
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_chat_service(container: ContainerDep) -> ChatService:
    """Chat use case."""
    return container.chat


def get_knowledge_service(container: ContainerDep) -> KnowledgeService:
    """Knowledge-base use case."""
    return container.knowledge


def get_livekit_service(container: ContainerDep) -> LiveKitService:
    """LiveKit token use case."""
    return container.livekit


async def require_api_key(
    container: ContainerDep, x_api_key: Annotated[str | None, Header()] = None
) -> None:
    """Reject the request unless ``X-API-Key`` matches a configured key (no keys = open)."""
    keys = container.settings.api_keys_list
    if not keys:
        return
    supplied = (x_api_key or "").encode()
    if not any(secrets.compare_digest(supplied, key.encode()) for key in keys):
        raise UnauthorizedError("Missing or invalid API key.")


ChatDep = Annotated[ChatService, Depends(get_chat_service)]
KnowledgeDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
LiveKitDep = Annotated[LiveKitService, Depends(get_livekit_service)]
