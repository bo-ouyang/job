from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_API = ROOT / "jobCollectionWebApi"


def source(relative_path: str) -> str:
    return (WEB_API / relative_path).read_text(encoding="utf-8")


def test_confirmed_unused_imports_are_removed():
    assert "RedirectResponse" not in source("admin/auth.py")
    assert "from schemas.token_schema import TokenData" not in source("dependencies.py")
    assert "aliased" not in source("crud/job.py")
    assert "from fastapi.staticfiles import StaticFiles" not in source("main.py")


def test_unmounted_static_app_fragment_is_removed():
    main_source = source("main.py")

    assert "static_dir =" not in main_source


def test_search_service_has_no_empty_elasticsearch_compatibility_methods():
    search_source = source("services/search_service.py")

    assert "async def upsert_job" not in search_source
    assert "async def delete_job" not in search_source


def test_retired_public_api_support_modules_are_removed():
    retired_modules = [
        "auth/jwt.py",
        "crud/application.py",
        "crud/company.py",
        "crud/skill.py",
        "schemas/application_schema.py",
        "schemas/favorite_schema.py",
    ]

    assert [path for path in retired_modules if (WEB_API / path).exists()] == []
