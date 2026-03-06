"""add model indexes for 2026-03-06 updates

Revision ID: 20260306_01
Revises:
Create Date: 2026-03-06 18:20:00
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260306_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_INDEXES: list[tuple[str, str, list[str]]] = [
    ("idx_admin_logs_user_action_created", "admin_logs", ["user_id", "action", "created_at"]),
    ("idx_admin_logs_model_object", "admin_logs", ["model_name", "object_id"]),
    ("idx_user_query_user_type_created", "user_query", ["user_id", "query_type", "created_at"]),
    ("idx_api_logs_path_status_created", "api_logs", ["path", "status_code", "created_at"]),
    ("idx_api_logs_user_created", "api_logs", ["user_id", "created_at"]),
    ("idx_task_logs_name_status_created", "task_logs", ["task_name", "status", "created_at"]),
    ("idx_task_logs_task_status_created", "task_logs", ["task_id", "status", "created_at"]),
    ("idx_app_user_status_created", "applications", ["user_id", "status", "created_at"]),
    ("idx_app_job_status_created", "applications", ["job_id", "status", "created_at"]),
    ("idx_boss_crawl_status_priority_created", "boss_crawl_task", ["status", "priority", "created_at"]),
    ("idx_boss_crawl_filter_status", "boss_crawl_task", ["filter_id", "status"]),
    ("idx_boss_filter_active_name", "boss_spider_filter", ["is_active", "filter_name"]),
    ("idx_boss_stu_major_status", "boss_stu_crawl_urls", ["major_name", "status"]),
    ("idx_boss_stu_status_created", "boss_stu_crawl_urls", ["status", "created_at"]),
    ("idx_cities_parent_level", "cities", ["parent_id", "level"]),
    ("idx_cities_name_pinyin", "cities", ["name", "pinyin"]),
    ("idx_cities_hot_parent_level", "cities_hot", ["parent_id", "level"]),
    ("idx_cities_hot_name_pinyin", "cities_hot", ["name", "pinyin"]),
    ("idx_company_industry_location", "company", ["industry", "location"]),
    ("idx_company_created_at", "company", ["created_at"]),
    ("idx_favorite_user_created", "favorite_jobs", ["user_id", "created_at"]),
    ("idx_follow_user_created", "follow_companies", ["user_id", "created_at"]),
    ("idx_fetch_fail_spider_created", "fetch_failures", ["spider", "created_at"]),
    ("idx_fetch_fail_method_status", "fetch_failures", ["method", "status_code"]),
    ("idx_industry_parent_level", "industries", ["parent_id", "level"]),
    ("idx_industry_name_first_char", "industries", ["name", "first_char"]),
    ("idx_jobs_city_industry_active", "jobs", ["city_code", "industry_code", "is_active"]),
    ("idx_jobs_company_active_created", "jobs", ["company_id", "is_active", "created_at"]),
    ("idx_jobs_ai_parsed_created", "jobs", ["ai_parsed", "created_at"]),
    ("idx_majors_parent_level", "majors", ["parent_id", "level"]),
    ("idx_majors_name_code", "majors", ["name", "code"]),
    ("idx_major_ind_rel_major_score", "major_industry_relations", ["major_id", "relevance_score"]),
    ("idx_major_ind_rel_name", "major_industry_relations", ["major_name"]),
    ("idx_messages_receiver_read_created", "messages", ["receiver_id", "is_read", "created_at"]),
    ("idx_messages_receiver_type_created", "messages", ["receiver_id", "type", "created_at"]),
    ("idx_payment_user_status_created", "payment_orders", ["user_id", "status", "created_at"]),
    ("idx_payment_status_paid_at", "payment_orders", ["status", "paid_at"]),
    ("idx_payment_type_created", "payment_orders", ["product_type", "created_at"]),
    ("idx_products_category_active", "products", ["category", "is_active"]),
    ("idx_products_active_created", "products", ["is_active", "created_at"]),
    ("idx_proxies_active_score", "proxies", ["is_active", "score"]),
    ("idx_proxies_protocol_active", "proxies", ["protocol", "is_active"]),
    ("idx_resumes_user_created", "resumes", ["user_id", "created_at"]),
    ("idx_resume_edu_resume_start", "resume_educations", ["resume_id", "start_date"]),
    ("idx_resume_work_resume_start", "resume_works", ["resume_id", "start_date"]),
    ("idx_resume_proj_resume_start", "resume_projects", ["resume_id", "start_date"]),
    ("idx_schools_name", "schools", ["name"]),
    ("idx_school_special_school_sid", "school_specials", ["school_id", "special_id"]),
    ("idx_school_special_level3_year", "school_specials", ["level3_code", "year"]),
    ("idx_school_intro_school_special", "school_special_intro", ["school_id", "special_id"]),
    ("idx_school_intro_status_label", "school_special_intro", ["status", "label"]),
    ("idx_skills_category_created", "skills", ["category", "created_at"]),
    ("idx_spider_boss_city_ind_page", "spider_boss_crawl_url", ["city_code", "industry_code", "page"]),
    ("idx_spider_boss_status_created", "spider_boss_crawl_url", ["status", "created_at"]),
    ("idx_system_cfg_category_active", "system_configs", ["category", "is_active"]),
    ("idx_user_wechats_user_openid", "user_wechats", ["user_id", "openid"]),
    ("idx_user_wechats_union_created", "user_wechats", ["unionid", "created_at"]),
    ("idx_users_role_status_created", "users", ["role", "status", "created_at"]),
    ("idx_users_status_last_login", "users", ["status", "last_login_at"]),
    ("idx_verif_phone_type_used", "verification_codes", ["phone", "code_type", "is_used"]),
    ("idx_verif_expires_at", "verification_codes", ["expires_at"]),
    ("idx_user_sess_user_active_exp", "user_sessions", ["user_id", "is_active", "expires_at"]),
    ("idx_user_sess_active_last", "user_sessions", ["is_active", "last_activity_at"]),
    ("idx_wallet_user_status", "user_wallets", ["user_id", "status"]),
    ("idx_wallet_status_updated", "user_wallets", ["status", "updated_at"]),
    ("idx_wallet_tx_wallet_created", "wallet_transactions", ["wallet_id", "created_at"]),
    ("idx_wallet_tx_wallet_type_created", "wallet_transactions", ["wallet_id", "transaction_type", "created_at"]),
]


def upgrade() -> None:
    for index_name, table_name, columns in NEW_INDEXES:
        op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    for index_name, table_name, _columns in reversed(NEW_INDEXES):
        op.drop_index(index_name, table_name=table_name)
