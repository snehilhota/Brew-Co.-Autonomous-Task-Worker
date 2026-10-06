from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_configuration_files_exist() -> None:
    """Catch accidental removal of the basic project setup files."""
    assert (PROJECT_ROOT / "README.md").is_file()
    assert (PROJECT_ROOT / ".env.example").is_file()
    assert (PROJECT_ROOT / ".gitignore").is_file()
