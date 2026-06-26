from pathlib import Path


def test_project_declares_python_311_runtime_baseline():
    project = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.11"' in project
    assert 'target-version = "py311"' in project
