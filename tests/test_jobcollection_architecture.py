import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRAPY_PACKAGE = ROOT / "jobCollection" / "jobCollection"


LEGACY_PATHS = [
    ROOT / "jobCollection" / "run_pipeline.py",
    SCRAPY_PACKAGE / "spiders" / "boss_base_spider.py",
    SCRAPY_PACKAGE / "spiders" / "boss_list_spider.py",
    SCRAPY_PACKAGE / "spiders" / "boss_detail_spider.py",
    SCRAPY_PACKAGE / "spiders" / "boss_detail_click_drission_spider.py",
    SCRAPY_PACKAGE / "simple_script" / "boss_mitm_addon.py",
    SCRAPY_PACKAGE / "simple_script" / "boss_list_gui_controller.py",
    SCRAPY_PACKAGE / "simple_script" / "boss_detail_gui_controller.py",
    SCRAPY_PACKAGE / "simple_script" / "boss_detail_gui_controller_backup.py",
    SCRAPY_PACKAGE / "simple_script" / "boss_detail_gui_controller_depressed.py",
    SCRAPY_PACKAGE / "simple_script" / "generate_urls.py",
    SCRAPY_PACKAGE / "simple_script" / "get_temp_proxy.py",
    SCRAPY_PACKAGE / "simple_script" / "generate_boss_stu_urls.py",
    SCRAPY_PACKAGE / "simple_script" / "parse_school_majors.py",
    SCRAPY_PACKAGE / "simple_script" / "seed_cities_hot.py",
    SCRAPY_PACKAGE / "simple_script" / "proxy_manager.py",
    SCRAPY_PACKAGE / "spiders" / "school.py",
    SCRAPY_PACKAGE / "items" / "school_item.py",
    SCRAPY_PACKAGE / "pipelines" / "school_pipeline.py",
    SCRAPY_PACKAGE / "middlewares" / "failure_logger_middleware.py",
    ROOT / "jobCollection" / "detail.html",
    ROOT / "jobCollection" / "school.html",
    ROOT / "jobCollection" / "task_detail_status.json",
    ROOT / "jobCollection" / "task_status.json",
    SCRAPY_PACKAGE / "simple_script" / "accounts.json",
]


def _spider_names():
    names = set()
    for path in (SCRAPY_PACKAGE / "spiders").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "name"
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    ):
                        names.add(node.value.value)
    return names


def test_only_retained_boss_spiders_remain():
    assert {name for name in _spider_names() if name.startswith("boss")} == {
        "boss_list_drission",
        "boss_detail_drission",
        "boss_major_discovery",
    }


def test_jobcollection_package_reload_has_no_reactor_side_effect():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, jobCollection; importlib.reload(jobCollection)",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_collectors_and_runtime_snapshots_are_removed():
    assert [str(path.relative_to(ROOT)) for path in LEGACY_PATHS if path.exists()] == []
    assert not (SCRAPY_PACKAGE / ".jobdir" / "school").exists()
    assert not (SCRAPY_PACKAGE / "simple_script" / "login_debug_account_1").exists()
    assert not list((SCRAPY_PACKAGE / "simple_script").glob("proxy_auth_plugin*"))


def test_proxy_configuration_has_no_repository_credentials():
    crawler_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            SCRAPY_PACKAGE / "boss" / "proxy.py",
            SCRAPY_PACKAGE / "spiders" / "boss_list_drission_spider.py",
            SCRAPY_PACKAGE / "spiders" / "boss_detail_drission_spider.py",
        ]
    )
    for secret_fragment in (
        "secret_id=",
        "signature=",
        "d2006816196",
        "xc1zag9a",
    ):
        assert secret_fragment not in crawler_source
    assert "simple_script.proxy_manager" not in crawler_source
    assert "from proxy_manager import proxy_manager" not in crawler_source


def test_obsolete_mysql_and_mitm_dependencies_are_fully_removed():
    mysql_manager = ROOT / "common" / "databases" / "MysqlManager.py"
    conftest_source = (ROOT / "pytest" / "conftest.py").read_text(encoding="utf-8")
    dependency_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [ROOT / "requirements.txt", ROOT / "jobCollectionWebApi" / "requirements.txt"]
    ).lower()

    assert not mysql_manager.exists()
    assert "PostgresManager" in conftest_source
    assert "MysqlManager" not in conftest_source
    assert "aiomysql" not in dependency_sources
    assert "mitmproxy" not in dependency_sources


def test_runtime_artifacts_are_ignored_but_account_example_is_trackable():
    ignored_paths = [
        "jobCollection/jobCollection/.jobdir/school/spider.state",
        "jobCollection/jobCollection/simple_script/login_debug_account_1/page.png",
        "jobCollection/jobCollection/simple_script/proxy_extensions/list_1/background.js",
        "jobCollection/jobCollection/simple_script/proxy_auth_plugin_list_1/background.js",
        "jobCollection/jobCollection/simple_script/accounts.json",
        "jobCollection/task_status.json",
        "jobCollection/detail.html",
    ]
    for ignored_path in ignored_paths:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, ignored_path

    example = "jobCollection/jobCollection/simple_script/accounts.example.json"
    example_result = subprocess.run(
        ["git", "check-ignore", example],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert example_result.returncode == 1
    assert (ROOT / example).exists()

    for unrelated_path in (
        "other-service/accounts.json",
        "other-service/task_worker_status.json",
    ):
        unrelated_result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", unrelated_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert unrelated_result.returncode == 1, unrelated_path
