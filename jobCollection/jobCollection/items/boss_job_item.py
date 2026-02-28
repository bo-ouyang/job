import scrapy

class BossJobItem(scrapy.Item):
    # Job Info
    job_name = scrapy.Field()
    job_desc = scrapy.Field() # Description if available (from detailed page, currently list only has fragments)
    salary_desc = scrapy.Field()
    job_experience = scrapy.Field()
    job_degree = scrapy.Field()
    skills = scrapy.Field() # List
    job_labels = scrapy.Field() # List
    welfare_list = scrapy.Field() # List
    
    # Location
    city_name = scrapy.Field()
    area_district = scrapy.Field()
    business_district = scrapy.Field()
    longitude = scrapy.Field()
    latitude = scrapy.Field()
    
    # Company Info
    brand_name = scrapy.Field()
    brand_logo = scrapy.Field()
    brand_stage_name = scrapy.Field()
    brand_scale_name = scrapy.Field()
    brand_industry = scrapy.Field()
    encrypt_brand_id = scrapy.Field()
    
    # Boss Info
    boss_name = scrapy.Field()
    boss_title = scrapy.Field()
    boss_avatar = scrapy.Field()
    
    # Meta / Extra
    encrypt_job_id = scrapy.Field() # for source_url
    security_id = scrapy.Field()
    
    # Context (passed from spider)
    city_code = scrapy.Field()
    industry_code = scrapy.Field()
    major_name = scrapy.Field()
    task_id = scrapy.Field()

class BossJobDetailItem(scrapy.Item):
    encrypt_job_id = scrapy.Field()
    job_desc = scrapy.Field()
    longitude = scrapy.Field()
    latitude = scrapy.Field()
    skills = scrapy.Field()
