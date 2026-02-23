# Scrapy settings for jonCollection project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html
import datetime
import os
import sys

BOT_NAME = "jobCollection"
SPIDER_MODULES = ["jobCollection.spiders"]
NEWSPIDER_MODULE = "jobCollection.spiders"



BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
print(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(BASE_DIR, '.env'))
curdir = os.getcwd()
ADDONS = {}
#redis 
# Redis 连接配置
# Redis 连接配置
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_KEY_PREFIX = 'job_analysis'

# Proxy Configuration
ENABLE_UPSTREAM_PROXY = False # Set to False to disable proxy usage entirely
# Format: http://username:password@host:port (or None to disable)
UPSTREAM_PROXY = None 
# Rotate IP every X minutes. Set to 0 to disable.
PROXY_ROTATE_MINUTES = 10

# # Scrapy Redis 配置
# SCRAPY_REDIS_URL = os.getenv('SCRAPY_REDIS_URL', 'redis://localhost:6379/1')

# # 分布式爬虫配置
# SCHEDULER = "scrapy_redis.scheduler.Scheduler"
# DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
# SCHEDULER_PERSIST = True
# SCHEDULER_QUEUE_CLASS = 'scrapy_redis.queue.PriorityQueue'

# # Redis 管道配置
# ITEM_PIPELINES = {
#     'scrapy_redis.pipelines.RedisPipeline': 300,
# }

# Redis 连接字符串
if REDIS_PASSWORD:
    REDIS_URL = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'
else:
    REDIS_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'

# Bloom Filter Configuration
# 2^25 bits = 32MB
BLOOM_BIT_SIZE_EXP = 26 
# 5 Hash Functions (seeds)
BLOOM_HASH_SEEDS = [5, 7, 11, 13, 31, 37]


DOWNLOAD_FILE = curdir+'//download//'
DOWNLOAD_IMG_PATH = DOWNLOAD_FILE+'//img//'
IMAGES_STORE = DOWNLOAD_FILE+'//img//'
FILES_STORE = DOWNLOAD_FILE+'//img//'
CSV_OUTPUT_FILE = DOWNLOAD_FILE+'//csv//'
SCRIPT_FILE = curdir+'//static//script//'



to_day = datetime.datetime.now()
LOG_LEVEL = 'INFO'
#LOG_LEVEL = 'DEBUG'
LOG_FILE_PATH = '{}/static/log/scrapy-{} {} {}.log'.format(curdir,to_day.year,to_day.month,to_day.day)
LOG_FILE  = LOG_FILE_PATH
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
ASYNCIO_EVENT_LOOP = "asyncio.SelectorEventLoop"

# DOWNLOAD_HANDLERS = {
#     "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
#     "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
# }

# PLAYWRIGHT_LAUNCH_OPTIONS = {
#     "headless": False,  # For debugging
#     "args": ["--disable-blink-features=AutomationControlled"]
# }

CONCURRENT_REQUESTS = 3

# Crawl responsibly by identifying yourself (and your website) on the user-agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Obey robots.txt rules
#ROBOTSTXT_OBEY = True

# Concurrency and throttling settings
#CONCURRENT_REQUESTS = 16
#CONCURRENT_REQUESTS_PER_DOMAIN = 1
#DOWNLOAD_DELAY = 1

# Disable cookies (enabled by default)
#COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
#TELNETCONSOLE_ENABLED = False

# Override the default request headers:
#DEFAULT_REQUEST_HEADERS = {
#    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#    "Accept-Language": "en",
#}

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
#SPIDER_MIDDLEWARES = {
#    "jonCollection.middlewares.JoncollectionSpiderMiddleware": 543,
#}

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html


# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
#EXTENSIONS = {
#    "scrapy.extensions.telnet.TelnetConsole": None,
#}

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
# ITEM_PIPELINES = {
#     "jobCollection.pipelines.boss_pipeline.BossJobPipeline": 300,
# }

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
#AUTOTHROTTLE_ENABLED = True
# The initial download delay
#AUTOTHROTTLE_START_DELAY = 5
# The maximum download delay to be set in case of high latencies
#AUTOTHROTTLE_MAX_DELAY = 60
# The average number of requests Scrapy should be sending in parallel to
# each remote server
#AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
# Enable showing throttling stats for every response received:
#AUTOTHROTTLE_DEBUG = False

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
#HTTPCACHE_ENABLED = True
#HTTPCACHE_EXPIRATION_SECS = 0
#HTTPCACHE_DIR = "httpcache"
#HTTPCACHE_IGNORE_HTTP_CODES = []
#HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
FEED_EXPORT_ENCODING = "utf-8"
