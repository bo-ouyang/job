from pathlib import Path


def test_pytest_configuration_declares_authoritative_test_and_import_paths():
    project_root = Path(__file__).resolve().parents[1]
    config = (project_root / "pyproject.toml").read_text(encoding="utf-8")

    assert 'testpaths = ["tests"]' in config
    assert 'pythonpath = [".", "jobCollectionWebApi", "jobCollection"]' in config
