from pathlib import Path
import builtins
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jobCollectionWebApi"))


def test_nginx_routes_admin_before_spa_fallback():
    config = (PROJECT_ROOT / "deploy" / "nginx" / "job.conf").read_text(
        encoding="utf-8"
    )

    admin_location = config.index("location ^~ /admin/")
    spa_location = config.index("location / {")

    assert admin_location < spa_location
    assert "proxy_pass http://127.0.0.1:8002;" in config[admin_location:spa_location]


def test_supervisor_runs_the_independent_admin_service():
    config = (PROJECT_ROOT / "deploy" / "supervisor" / "jobcollection.conf").read_text(
        encoding="utf-8"
    )

    assert "[program:job-admin]" in config
    assert "uvicorn main_admin:app --host 127.0.0.1 --port 8002" in config
    assert "autostart=true" in config


def test_admin_can_start_without_optional_babel_dependency(monkeypatch):
    from admin import setup as admin_setup

    real_import = builtins.__import__

    def import_without_babel(name, *args, **kwargs):
        if name == "babel":
            raise ModuleNotFoundError("No module named 'babel'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_babel)

    assert admin_setup.build_admin_i18n_config() is None


def test_admin_navigation_labels_are_valid_chinese_text():
    source = (PROJECT_ROOT / "jobCollectionWebApi" / "admin" / "setup.py").read_text(
        encoding="utf-8"
    )

    for label in (
        "招聘平台后台管理",
        "首页",
        "行业分类",
        "AI服务价格",
        "系统配置",
        "操作日志",
        "任务日志",
    ):
        assert label in source

    assert "鎷涜仒" not in source
