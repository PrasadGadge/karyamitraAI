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
    assert captured["reload_excludes"] == [".venv/*", "evaluation_runs/*"]
    assert run_dev.PROJECT_DIR == Path(run_dev.__file__).resolve().parent
