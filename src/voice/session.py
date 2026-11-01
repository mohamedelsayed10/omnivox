"""Voice session assembly: the agent, the session and the spoken error fallback."""

from livekit.agents import Agent, AgentSession, llm, stt, tts, vad
from livekit.agents.voice import events

from config.logger import get_logger
from src.prompts.agent import ERROR_SPEECH

logger = get_logger(__name__)


class OmniAgent(Agent):
    """Greets the caller. All instructions live in the graph's prompt, not here."""

    def __init__(self, greeting: str) -> None:
        super().__init__(instructions="")
        self._greeting = greeting

    async def on_enter(self) -> None:
        """Speak the greeting as soon as the agent is active."""
        self.session.say(self._greeting)


def build_session(
    *,
    stt_plugin: stt.STT,
    tts_plugin: tts.TTS,
    vad_plugin: vad.VAD,
    llm_plugin: llm.LLM,
    turn_handling: object,
) -> AgentSession:
    """Create the session: VAD -> STT -> turn detection -> LLM adapter -> TTS."""
    return AgentSession(
        stt=stt_plugin,
        tts=tts_plugin,
        vad=vad_plugin,
        llm=llm_plugin,
        turn_handling=turn_handling,
    )


def install_error_fallback(session: AgentSession) -> None:
    """Tell the caller when the LLM fails for good, instead of leaving silence."""

    def on_error(event: events.ErrorEvent) -> None:
        error = event.error
        if isinstance(error, llm.LLMError) and not error.recoverable:
            logger.warning("LLM failed permanently, speaking fallback")
            try:
                session.say(ERROR_SPEECH)
            except RuntimeError as exc:
                logger.warning("Fallback speech not possible: %s", exc)

    session.on("error", on_error)
