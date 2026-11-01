"""LiveKit agent worker. Run with ``python -m src.voice.worker start`` (or ``dev``).

Second composition root next to ``src/app.py``: it wires the shared runtime into a voice session.
"""

from livekit.agents import AgentServer, JobContext, JobProcess, cli
from livekit.plugins import langchain

from config.logger import get_logger, set_request_id, setup_logging
from config.settings import Settings, get_settings
from src.ai_models.asr import SpeechToText
from src.ai_models.tts import TextToSpeech
from src.ai_models.turn import TurnDetection
from src.ai_models.vad import VoiceActivityDetector
from src.composition import build_runtime
from src.graph.trace import build_run_config
from src.voice.inspector import Inspector
from src.voice.session import OmniAgent, build_session, install_error_fallback
from src.voice.speakable import SpeakableGraph

logger = get_logger(__name__)

VAD_KEY = "vad"
VOICE_TAG = "voice"


def prewarm(proc: JobProcess) -> None:
    """Load the heavy, loop-independent model once per worker process."""
    settings = get_settings()
    setup_logging(settings, exclusive=True)
    proc.userdata[VAD_KEY] = VoiceActivityDetector(settings).load()
    logger.info("Voice worker process ready (VAD loaded)")


async def entrypoint(ctx: JobContext) -> None:
    """Run one voice session for the room this job was dispatched to."""
    settings = get_settings()
    set_request_id(ctx.room.name)
    runtime = build_runtime(settings)
    ctx.add_shutdown_callback(runtime.aclose)

    speech_to_text = SpeechToText(settings)
    text_to_speech = TextToSpeech(settings)
    turn_detection = TurnDetection(settings)
    vad_model = VoiceActivityDetector(settings)
    await ctx.connect()

    inspector = Inspector(
        ctx.room,
        settings,
        runtime.tracing,
        [
            runtime.llm.info,
            speech_to_text.info,
            text_to_speech.info,
            vad_model.info,
            turn_detection.info,
        ],
    )
    inspector.start()
    ctx.add_shutdown_callback(inspector.aclose)

    config = build_run_config(
        settings,
        runtime.tracing,
        session_id=ctx.room.name,
        request_id=ctx.job.id,
        handlers=[inspector.graph_handler()],
        tags=[VOICE_TAG],
    )
    session = build_session(
        stt_plugin=speech_to_text.build(),
        tts_plugin=text_to_speech.build(),
        vad_plugin=ctx.proc.userdata[VAD_KEY],
        llm_plugin=langchain.LLMAdapter(SpeakableGraph(runtime.build_graph()), config=config),
        turn_handling=turn_detection.options(),
    )
    inspector.attach(session)
    install_error_fallback(session)
    await session.start(agent=OmniAgent(settings.AGENT_GREETING), room=ctx.room)
    logger.info("Voice session started in room %s", ctx.room.name)


def create_server(settings: Settings) -> AgentServer:
    """Create the worker and register the room entrypoint."""
    server = AgentServer(
        ws_url=settings.LIVEKIT_URL,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET.get_secret_value(),
        num_idle_processes=settings.WORKER_IDLE_PROCESSES,
        port=settings.WORKER_PORT,
        setup_fnc=prewarm,
    )
    server.rtc_session()(entrypoint)
    return server


server = create_server(get_settings())

if __name__ == "__main__":
    cli.run_app(server)
