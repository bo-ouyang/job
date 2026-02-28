from starlette_admin.contrib.sqla import Admin
from starlette_admin import I18nConfig
import os
from .auth import AdminAuth
from .views import (
    HomeView, UserView, JobView, CompanyView, ResumeView, 
    FavoriteJobView, IndustryView, SkillsView, 
    AdminLogView, TaskLogView, 
    BossSpiderFilterView, BossCrawlTaskView,
    ProxyView, ProductView, SystemConfigView
)
from common.databases.models.user import User
from common.databases.models.job import Job
from common.databases.models.company import Company
from common.databases.models.resume import Resume
from common.databases.models.favorite import FavoriteJob
from common.databases.models.industry import Industry
from common.databases.models.skills import Skills
from common.databases.models.admin_log import AdminLog
from common.databases.models.analysis import TaskLog
from common.databases.models.boss_spider_filter import BossSpiderFilter
from common.databases.models.boss_crawl_task import BossCrawlTask
from common.databases.models.proxy import Proxy
# Ensure related models are loaded for User relationships
from common.databases.models.payment import PaymentOrder
from common.databases.models.wallet import UserWallet
from common.databases.models.product import Product
from common.databases.models.system_config import SystemConfig

def setup_admin(app, engine):
    # Locate templates directory
    # admin/setup.py -> jobCollectionWebApi/admin -> jobCollectionWebApi
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    templates_dir = os.path.join(project_root, "templates")

    admin = Admin(
        engine, 
        title="招聘平台后台管理",
        base_url="/admin",
        auth_provider=AdminAuth(),
        i18n_config=I18nConfig(default_locale="zh_CN"),
        index_view=HomeView(label="主页", icon="fa fa-home", path="/", template_path="admin/dashboard.html"),
        templates_dir=templates_dir,
        middlewares=[] 
    )
    
    admin.add_view(UserView(User))
    admin.add_view(JobView(Job))
    admin.add_view(CompanyView(Company))
    admin.add_view(ResumeView(Resume))
    admin.add_view(FavoriteJobView(FavoriteJob))
    admin.add_view(IndustryView(Industry, label="行业分类"))
    admin.add_view(SkillsView(Skills, label="技能标签"))
    
    admin.add_view(ProductView(Product, label="AI服务价格", icon="fa fa-tags"))
    admin.add_view(SystemConfigView(SystemConfig, label="系统配置", icon="fa fa-sliders-h"))

    # Crawler Module
    admin.add_view(BossSpiderFilterView(BossSpiderFilter, icon="fa fa-filter"))
    admin.add_view(BossCrawlTaskView(BossCrawlTask, icon="fa fa-spider"))
    admin.add_view(ProxyView(Proxy, icon="fa fa-globe"))
    
    admin.add_view(AdminLogView(AdminLog, label="操作日志", icon="fa fa-history"))
    admin.add_view(TaskLogView(TaskLog, label="任务日志", icon="fa fa-tasks"))
    
    admin.mount_to(app)
