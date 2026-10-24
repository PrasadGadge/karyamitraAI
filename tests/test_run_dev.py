from pathlib import Path

import run_dev


def test_runner_uses_programmatic_reload_configuration(monkeypatch):
    captured = {}
    monkeypatch.setattr(run_dev.uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))
    run_dev.run(8123)
    assert captured["app"] == "app:app"
    assert captured["reload"] is True
    assert captured["port"] == 8123
    assert captured["reload_dirs"] == [str(run_dev.PROJECT_DIR)]
    assert captured["reload_excludes"] == [str(run_dev.PROJECT_DIR / ".venv"), str(run_dev.PROJECT_DIR / "evaluation_runs")]
    assert Path(run_dev.PROJECT_DIR).name == "KaryaMitra AI"
