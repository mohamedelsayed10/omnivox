"""Session helpers and worker wiring (no LiveKit server needed)."""

import time
from types import SimpleNamespace

from livekit.agents import AgentServer, llm
from livekit.agents.voice import events

from src.prompts.agent import ERROR_SPEECH
from src.voice import worker
from src.voice.session import OmniAgent, install_error_fallback


class FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.spoken: list[str] = []

    def on(self, name: str, callback=None):
        self.handlers[name] = callback
        return callback

    def say(self, text: str):
        self.spoken.append(text)


def llm_error(recoverable: bool) -> events.ErrorEvent:
    error = llm.LLMError(
        timestamp=time.time(), label="x", error=Exception("down"), recoverable=recoverable
    )
    return events.ErrorEvent(error=error, source=SimpleNamespace())


def test_permanent_llm_failure_is_spoken_to_the_caller():
    session = FakeSession()
    install_error_fallback(session)
    session.handlers["error"](llm_error(recoverable=False))
    assert session.spoken == [ERROR_SPEECH]


def test_recoverable_and_non_llm_errors_stay_silent():
    session = FakeSession()
    install_error_fallback(session)
    session.handlers["error"](llm_error(recoverable=True))
    other = events.ErrorEvent(error=Exception("tts"), source=SimpleNamespace())
    session.handlers["error"](other)
    assert session.spoken == []


def test_agent_holds_no_instructions_of_its_own():
    agent = OmniAgent("Hello!")
    assert agent.instructions == ""


def test_server_is_built_from_settings(settings):
    server = worker.create_server(settings)
    assert isinstance(server, AgentServer)
    assert server._entrypoint_fnc is worker.entrypoint
    assert server._setup_fnc is worker.prewarm


def test_prewarm_loads_the_vad_into_process_state(settings, monkeypatch):
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "setup_logging", lambda *args, **kwargs: None)
    proc = SimpleNamespace(userdata={})
    worker.prewarm(proc)
    assert worker.VAD_KEY in proc.userdata
