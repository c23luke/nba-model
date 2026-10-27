import pytest


@pytest.fixture(autouse=True)
def _no_restart_cutoff(monkeypatch):
    """The live board starts counting at engine.run.RESTART_UTC (2026-10-27). The test fixtures are
    2025 games, so the cutoff is switched off here; test_restart_* checks it on its own."""
    import engine.run as R
    monkeypatch.setattr(R, "RESTART_UTC", "")
