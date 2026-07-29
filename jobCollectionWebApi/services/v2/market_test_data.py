"""Deterministic display fixtures for market dimensions absent from storage.

These values are never persisted to business tables. The dashboard service
labels every field sourced from this module through dataStatus.
"""

MARKET_TEST_DATA = {
    "hero_signals": [
        {"label": "人工智能", "value": "+24.8%"},
        {"label": "先进制造", "value": "+18.3%"},
    ],
    "trend": {
        "years": ["8月", "10月", "12月", "2月", "4月", "6月"],
        "series": [
            {"name": "人工智能", "values": [92, 108, 124, 148, 171, 188], "color": "#176bff"},
            {"name": "新能源", "values": [68, 76, 91, 110, 132, 151], "color": "#18a88c"},
            {"name": "互联网", "values": [105, 108, 113, 116, 122, 126], "color": "#78899f"},
        ],
    },
    "city_salaries": [
        {"name": "北京", "value": 18.6},
        {"name": "上海", "value": 17.5},
        {"name": "深圳", "value": 16.9},
        {"name": "杭州", "value": 15.4},
        {"name": "广州", "value": 13.3},
    ],
    "skills": [
        {"name": "Python", "value": 68},
        {"name": "数据分析", "value": 61},
        {"name": "SQL", "value": 53},
        {"name": "AI 应用", "value": 49},
        {"name": "项目管理", "value": 42},
        {"name": "产品设计", "value": 35},
    ],
    "salary_distribution": [
        {"label": "8K 以下", "value": 12},
        {"label": "8–12K", "value": 24},
        {"label": "12–18K", "value": 31, "featured": True},
        {"label": "18–25K", "value": 21},
        {"label": "25–35K", "value": 9},
        {"label": "35K 以上", "value": 3},
    ],
    "salary_summary": {"median": 12680, "p75": 21300},
    "talent_structure": {
        "education": [
            {"label": "不限", "value": 14},
            {"label": "本科", "value": 62},
            {"label": "硕士", "value": 19},
            {"label": "其他", "value": 5},
        ],
        "experience": [
            {"label": "应届 / 在校", "value": 18},
            {"label": "1–3 年", "value": 42},
            {"label": "3–5 年", "value": 27},
            {"label": "5 年以上", "value": 13},
        ],
    },
    "city_matrix": [
        {"city": "杭州", "growth": 19.4, "salary": 15.4, "size": 76, "tone": "blue"},
        {"city": "深圳", "growth": 16.8, "salary": 16.9, "size": 66, "tone": "green"},
        {"city": "上海", "growth": 12.8, "salary": 17.5, "size": 68, "tone": "violet"},
        {"city": "北京", "growth": 10.6, "salary": 18.6, "size": 70, "tone": "navy"},
        {"city": "成都", "growth": 15.1, "salary": 12.8, "size": 60, "tone": "amber"},
    ],
    "signals": [
        {"type": "需求加速", "title": "AI 产品经理", "detail": "岗位发布量连续 6 周上升", "delta": "+28.4%", "tone": "up", "icon": "↗"},
        {"type": "薪资上涨", "title": "新能源算法", "detail": "P50 月薪达到 23.6K", "delta": "+11.2%", "tone": "salary", "icon": "¥"},
        {"type": "新兴技能", "title": "RAG / Agent", "detail": "进入技能需求展示榜", "delta": "+46.8%", "tone": "skill", "icon": "⌁"},
        {"type": "需求降温", "title": "传统运营岗位", "detail": "低经验岗位占比持续收缩", "delta": "-8.3%", "tone": "down", "icon": "↓"},
    ],
    "rankings": [
        {"name": "人工智能 / 大模型", "growth": "+24.8%", "salary": "¥21.6K", "gap": "高", "score": "92.4"},
        {"name": "新能源与储能", "growth": "+18.3%", "salary": "¥15.8K", "gap": "高", "score": "87.1"},
        {"name": "智能制造", "growth": "+15.7%", "salary": "¥14.9K", "gap": "中高", "score": "83.6"},
        {"name": "跨境电商", "growth": "+12.2%", "salary": "¥13.4K", "gap": "中", "score": "78.9"},
    ],
}
