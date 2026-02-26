# Job Index Mapping
JOB_INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,  # 单节点开发环境
        "analysis": {
            "analyzer": {
                "ik_smart_analyzer": {
                    "type": "custom",
                    "tokenizer": "ik_smart"  # 假设已安装 IK 分词器，如果没有则需要回退到 standard
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "id": {"type": "long"},
            "title": {
                "type": "text", 
                "analyzer": "ik_max_word", 
                "search_analyzer": "ik_smart",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256}
                }
            },
            "description": {
                "type": "text", 
                "analyzer": "ik_max_word", 
                "search_analyzer": "ik_smart"
            },
            "requirements": {
                "type": "text", 
                "analyzer": "ik_max_word", 
                "search_analyzer": "ik_smart"
            },
            "salary_min": {"type": "float"},
            "salary_max": {"type": "float"},
            "city": {"type": "keyword"},
            "district": {"type": "keyword"},
            "experience": {"type": "keyword"},
            "education": {"type": "keyword"},
            "company_name": {
                "type": "text",
                "analyzer": "ik_max_word",
                "fields": {
                    "keyword": {"type": "keyword"}
                }
            },
            "industry": {"type": "keyword"},
            "industry_code": {"type": "integer"},
            "city_code": {"type": "integer"},
            "salary_unit": {"type": "keyword"},
            "salary_desc": {"type": "keyword"},
            "ai_summary": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart"
            },
            "ai_skills": {"type": "keyword"},
            "ai_benefits": {"type": "keyword"},
            "job_labels": {"type": "keyword"},
            "work_type": {"type": "keyword"},
            "boss_name": {"type": "keyword"},
            "boss_title": {"type": "keyword"},
            "welfare": {"type": "keyword"},
            "skills": {"type": "keyword"}, # 列表
            "tags": {"type": "keyword"},   # 列表
            "publish_date": {"type": "date"},
            "created_at": {"type": "date"},
            "location": {"type": "keyword"}
        }
    }
}
