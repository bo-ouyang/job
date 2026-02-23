import scrapy

from jobCollection.items.school_item import (
    SchoolItem,
    SchoolSpecialItem,
    SpecialIntroItem
)

class School(scrapy.Spider):
    name = "school"
    school_count = 0
    specital_count = 0
    start_urls = [
        "https://static-data.gaokao.cn/www/2.0/info/linkage.json?a=www.gaokao.cn"
    ]
    custom_settings = {
        "ITEM_PIPELINES": {
            'jobCollection.pipelines.school_pipeline.SchoolPipeline': 1,
           
        },
        'DOWNLOADER_MIDDLEWARES' : {
            "jobCollection.middlewares.failure_logger_middleware.FailureLoggerMiddleware": 1,
        },
        # 并发控制（等价 Semaphore）
        'CONCURRENT_REQUESTS': 100,
        'CONCURRENT_REQUESTS_PER_DOMAIN' : 16,

        # 限速（非常重要）
        'DOWNLOAD_DELAY' : 0.2,
        'RANDOMIZE_DOWNLOAD_DELAY' : True,

        # 超时
        'DOWNLOAD_TIMEOUT' : 15,

        # 失败重试
        'RETRY_ENABLED' : True,
        'RETRY_TIMES' : 3,
        'RETRY_HTTP_CODES' : [403, 429, 500, 502, 503, 504],

        # Headers
        'DEFAULT_REQUEST_HEADERS' : {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        },
        # 断点续爬目录（核心）
        'JOBDIR' : "jobCollection/.jobdir/school",

        # # 强烈建议开启
        # 'SCHEDULER_PERSIST' : True,
        # 'DUPEFILTER_CLASS' : "scrapy.dupefilters.RFPDupeFilter"
       

    }
    async def parse(self, response):
        data = response.json()
        schools = data["data"]["school"]
        for school in schools:
            school_id = int(school["school_id"])
            url = (
                f"https://static-data.gaokao.cn/www/2.0/school/"
                f"{school_id}/pc_special.json?a=www.gaokao.cn"
            )
            
            
            yield scrapy.Request(
                url=url,
                callback=self.parse_school_specials,
                meta={"school_id": school_id}
            )
            yield SchoolItem(
                id=school_id,
                name=school["name"]
            )
            print(url)
            

    async def parse_school_specials(self, response):
        print(self.specital_count)
        school_id = response.meta["school_id"]
        data = response.json()
        specials = data["data"]["special_detail"]
        #print(specials['1'][0])
        data = specials['2']  if  specials.get('1',[]) == [] else specials['1']
        if data:
            for sp in data:
                yield SchoolSpecialItem(
                    id=int(sp.get("id", 0) or 0),  # 提供默认值，并处理None
                    school_id=school_id,
                    special_id=int(sp.get("special_id", 0) or 0),
                    special_name=sp.get("special_name", ""),
                    code=sp.get("code", ""),
                    level1_name=sp.get("type_name", ""),
                    level2_name=sp.get("level2_name", ""),
                    level3_name=sp.get("level3_name", ""),
                    level3_code=sp.get("level3_code", ""),
                    nation_feature=sp.get("nation_feature", ""),
                    province_feature=sp.get("province_feature", ""),
                    is_important=sp.get("is_important", ""),
                    limit_year=sp.get("limit_year", ""),
                    year=sp.get("year", ""),
                    xueke_rank=sp.get("xueke_rank", ""),
                    xueke_rank_score=sp.get("xueke_rank_score", ""),
                    ruanke_rank=sp.get("ruanke_rank", ""),
                    ruanke_level=sp.get("ruanke_level", ""),
                    is_video=sp.get("is_video", ""),
                )

                detail_url = (
                    f"https://static-data.gaokao.cn/www/2.0/school/"
                    f"{school_id}/special/{sp['id']}.json?a=www.gaokao.cn"
                )
                self.specital_count += 1
                yield scrapy.Request(
                    url=detail_url,
                    callback=self.parse_special_detail,
                    meta={"school_id": school_id}
                )

    async def parse_special_detail(self, response):
        school_id = response.meta["school_id"]
        data = response.json()["data"]

        yield SpecialIntroItem(
            id=int(data.get("id", 0) or 0),
            school_id=school_id,  # 这个应该是外部传入的，不需要从data获取
            special_id=int(data.get("special_id", 0) or 0),
            name=data.get("name", ""),
            degree=data.get("degree"),
            content=data.get("content", ""),
            job=data.get("job"),
            status=data.get("status", ""),  # 如果status是必需字段，给默认值
            label=data.get("label", ""),    # 如果label是必需字段，给默认值
            elective=data.get("elective", []),
            video=data.get("video", []),
            satisfaction=data.get("satisfaction", {}),
            is_video=data.get("is_video"),
        )
