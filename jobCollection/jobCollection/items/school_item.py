import scrapy


class SchoolItem(scrapy.Item):
    id = scrapy.Field()
    name = scrapy.Field()


class SchoolSpecialItem(scrapy.Item):
    id = scrapy.Field()
    school_id = scrapy.Field()
    special_id = scrapy.Field()
    special_name = scrapy.Field()
    code = scrapy.Field()
    level1_name = scrapy.Field()
    level2_name = scrapy.Field()
    level3_name = scrapy.Field()
    level3_code = scrapy.Field()
    nation_feature = scrapy.Field()
    province_feature = scrapy.Field()
    is_important = scrapy.Field()
    limit_year = scrapy.Field()
    year = scrapy.Field()
    xueke_rank = scrapy.Field()
    xueke_rank_score = scrapy.Field()
    ruanke_rank = scrapy.Field()
    ruanke_level = scrapy.Field()
    is_video = scrapy.Field()


class SpecialIntroItem(scrapy.Item):
    id = scrapy.Field()
    school_id = scrapy.Field()
    special_id = scrapy.Field()
    name = scrapy.Field()
    degree = scrapy.Field()
    content = scrapy.Field()
    job = scrapy.Field()
    status = scrapy.Field()
    label = scrapy.Field()
    elective = scrapy.Field()
    video = scrapy.Field()
    satisfaction = scrapy.Field()
    is_video = scrapy.Field()
