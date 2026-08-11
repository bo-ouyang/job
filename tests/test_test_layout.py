from pathlib import Path


def test_legacy_pytest_directory_is_not_part_of_the_test_suite():
    project_root = Path(__file__).resolve().parents[1]

    assert not (project_root / "pytest").exists()
