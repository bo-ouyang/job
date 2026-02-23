from .base import Base
from .job import Job
from .company import Company
from .skills import Skills
from .analysis import AnalysisResult, UserQuery, APILog, TaskLog
from .user import User, VerificationCode, UserSession, UserRole, UserStatus, UserWechat
from .school import School
from .school_special import SchoolSpecial
from .school_special_intro import SchoolSpecialIntro
from .industry import Industry
from .admin_log import AdminLog
from .resume import Resume, Education, WorkExperience, ProjectExperience
from .favorite import FavoriteJob, FollowCompany
from .application import Application
from .message import Message
from .city import City
from .boss_crawl_task import BossCrawlTask
from .boss_spider_filter import BossSpiderFilter
from .fetch_failure import FetchFailure
from .payment import PaymentOrder
from .wallet import UserWallet, WalletTransaction
from .product import Product
from .spider_boss_crawl_url import SpiderBossCrawlUrl
from .major import Major, MajorIndustryRelation
from .boss_stu_crawl_url import BossStuCrawlUrl

__all__ = [
    'Base',
    'Job',
    'Company', 
    'Skills',
    'AnalysisResult',
    'UserQuery',
    'APILog',
    'TaskLog',
    'User',
    'VerificationCode',
    'UserSession',
    'UserRole',
    'UserStatus',
    'UserWechat',
    'School',
    'SchoolSpecial',
    'SchoolSpecialIntro',
    'Industry',
    'AdminLog',
    'Resume',
    'Education',
    'WorkExperience',
    'ProjectExperience',
    'FavoriteJob',
    'FollowCompany',
    'Application',
    'Message',
    'City',
    'BossCrawlTask',
    'BossSpiderFilter',
    'FetchFailure',
    'PaymentOrder',
    'UserWallet',
    'WalletTransaction',
    'Product',
    'SpiderBossCrawlUrl',
    'Major',
    'MajorIndustryRelation',
    'BossStuCrawlUrl'
]
