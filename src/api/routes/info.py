"""Non-secret runtime information for the GUI."""

from fastapi import APIRouter

from src import __version__
from src.api.deps import ContainerDep
from src.api.schemas.responses import ErrorResponse, InfoResponse

router = APIRouter(tags=["info"])


@router.get(
    "/info",
    response_model=InfoResponse,
    status_code=200,
    responses={401: {"model": ErrorResponse}},
)
async def info(container: ContainerDep) -> InfoResponse:
    """Models and switches the service runs with. Contains no secrets."""
    settings = container.settings
    by_kind = {item.kind: item for item in container.model_infos()}
    return InfoResponse(
        app_name=settings.APP_NAME,
        version=__version__,
        llm_model=by_kind["llm"].model,
        stt_provider=by_kind["stt"].provider,
        stt_model=by_kind["stt"].model,
        tts_provider=by_kind["tts"].provider,
        tts_model=by_kind["tts"].model,
        embedding_model=by_kind["embedding"].model,
        turn_detector=settings.TURN_DETECTOR,
        tracing_provider=settings.TRACING_PROVIDER,
        auth_required=settings.auth_required,
        knowledge_base_configured=container.runtime.embeddings.configured,
    )
