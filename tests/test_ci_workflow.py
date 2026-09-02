"""Lightweight unit-test workflow only — no deploy jobs."""

from pathlib import Path

import yaml


def test_pytest_workflow_is_ubuntu_unit_tests_only():
    path = Path(".github/workflows/pytest.yml")
    assert path.is_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert set(jobs) == {"unit"}
    job = jobs["unit"]
    assert job["runs-on"] == "ubuntu-latest"
    run_blobs = []
    for step in job["steps"]:
        if "run" in step:
            run_blobs.append(step["run"])
    text = "\n".join(run_blobs).lower()
    assert "pytest" in text
    assert "deploy" not in text
    blob = path.read_text(encoding="utf-8").lower()
    assert "deploy" not in blob
    assert "macos" not in blob
