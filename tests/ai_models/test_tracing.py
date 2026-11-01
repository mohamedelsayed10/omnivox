"""Tracing is a no-op when off and never raises when on."""

from datetime import datetime, timezone

from langchain_core.tracers.langchain import LangChainTracer

from src.ai_models.tracing import Tracing


def record(tracing: Tracing) -> None:
    tracing.record_run(
        "voice.turn",
        run_type="chain",
        inputs={"turn": 1},
        outputs={"total_ms": 900.0},
        started_at=datetime.now(timezone.utc),
    )


def test_off_returns_no_callbacks_and_ignores_runs(settings):
    tracing = Tracing(settings)
    assert tracing.enabled is False
    assert tracing.get_callbacks() == []
    record(tracing)
    tracing.flush()


def test_langsmith_returns_a_tracer(make_settings):
    settings = make_settings(
        TRACING_PROVIDER="langsmith",
        LANGSMITH_API_KEY="lsv2_pt_dummy_dummy_dummy_dummy",
        LANGSMITH_PROJECT="omnivox-tests",
    )
    tracing = Tracing(settings)
    assert tracing.enabled is True
    (tracer,) = tracing.get_callbacks()
    assert isinstance(tracer, LangChainTracer)
    assert tracer.project_name == "omnivox-tests"


def test_tracing_errors_are_swallowed(make_settings):
    settings = make_settings(
        TRACING_PROVIDER="langsmith", LANGSMITH_API_KEY="lsv2_pt_dummy_dummy_dummy_dummy"
    )
    tracing = Tracing(settings)

    class Broken:
        def create_run(self, **kwargs):
            raise RuntimeError("network down")

        def flush(self):
            raise RuntimeError("network down")

    tracing._client = Broken()
    record(tracing)
    tracing.flush()
