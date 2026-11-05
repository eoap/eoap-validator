from __future__ import annotations

import tomllib
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = ["3.11", "3.12", "3.13", "3.14", "3.15"]


def test_python_support_contract_is_synchronized() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    workflow = YAML(typ="safe").load(
        (ROOT / ".github/workflows/package.yaml").read_text()
    )

    assert project["project"]["requires-python"] == ">=3.11,<3.16"
    classifiers = project["project"]["classifiers"]
    assert [
        classifier.removeprefix("Programming Language :: Python :: ")
        for classifier in classifiers
        if classifier.startswith("Programming Language :: Python :: 3.")
    ] == SUPPORTED
    assert project["tool"]["ruff"]["target-version"] == "py311"
    assert project["tool"]["mypy"]["python_version"] == "3.11"
    assert (
        project["tool"]["hatch"]["envs"]["test-matrix"]["matrix"][0]["python"]
        == SUPPORTED
    )

    jobs = workflow["jobs"]
    assert jobs["test"]["strategy"]["matrix"]["python"] == SUPPORTED
    assert jobs["publish"]["steps"][1]["with"]["python-version"] == "3.11"

    for path in (ROOT / "README.md", ROOT / "docs/how-to/cli.md"):
        text = path.read_text()
        assert "Python 3.11 through 3.15" in text
        assert "Python 3.10" not in text

    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "Add Python 3.15 support" in changelog
    assert "Remove Python 3.10 support" in changelog
