import logging
import hashlib
import os
import redis
from scrapy.exceptions import DropItem

logger = logging.getLogger(__name__)

class RedisBloomFilter:
    def __init__(self, server, key, bit_size, seeds):
        self.bit_size = bit_size
        self.seeds = seeds
        self.server = server
        self.key = key

    def get_hash_points(self, value):
        if not value:
            return []
        """Generate k hash points."""
        encoded = str(value).encode("utf-8")
        points = []
        for seed in self.seeds:
            digest = hashlib.blake2b(
                encoded,
                digest_size=8,
                person=str(seed).encode("ascii")[:16],
            ).digest()
            points.append(int.from_bytes(digest, "big") % self.bit_size)
        return points

    def is_contains(self, value):
        points = self.get_hash_points(value)
        if not points:
            return False
        
        name = self.key
        pipe = self.server.pipeline()
        for loc in points:
            pipe.getbit(name, loc)
        results = pipe.execute()
        return all(results)

    def insert(self, value):
        points = self.get_hash_points(value)
        if not points:
            return

        name = self.key
        pipe = self.server.pipeline()
        for loc in points:
            pipe.setbit(name, loc, 1)
        pipe.execute()

class RedisDeduplicationPipeline:
    def __init__(self, redis_host, redis_port, redis_db, redis_password, bit_size_exp, seeds):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.bit_size_exp = bit_size_exp
        self.seeds = seeds
        self.server = None
        self.bf = None
        self.bf_key = "boss:bloomfilter"
        self.bf_ttl_seconds = 172800
        self._ttl_applied = False

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls(
            redis_host=crawler.settings.get('REDIS_HOST', 'localhost'),
            redis_port=crawler.settings.get('REDIS_PORT', 6379),
            redis_db=crawler.settings.get('REDIS_DB', 0),
            redis_password=crawler.settings.get('REDIS_PASSWORD'),
            bit_size_exp=crawler.settings.getint('BLOOM_BIT_SIZE_EXP', 26), # Default 2^26 = ~64M bits ~ 8MB
            seeds=crawler.settings.getlist('BLOOM_HASH_SEEDS', [5, 7, 11, 13, 31]) # Default 5 seeds
        )
        pipeline.crawler = crawler
        return pipeline

    def open_spider(self, spider):
        try:
            self.server = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=False 
            )
            # Test Connection
            self.server.ping()
            
            # Stable daily window, separated by spider and automatically expired.
            import datetime
            run_id = datetime.datetime.now().strftime('%Y%m%d')
            self.bf_key = f"boss:bloomfilter:{spider.name}:{run_id}"

            # Initialize Bloom Filter with config
            bit_size = 1 << self.bit_size_exp
            self.bf = RedisBloomFilter(self.server, self.bf_key, bit_size, self.seeds)
            self.bf_ttl_seconds = int(os.getenv("BOSS_BLOOM_TTL_SECONDS", "172800"))
            self._ttl_applied = False
            
            logger.info(f"Redis Bloom Filter Connected. Key: {self.bf_key} Size: 2^{self.bit_size_exp} ({bit_size/8/1024/1024:.2f} MB)")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}. Deduplication disabled.")
            self.server = None

    def process_item(self, item, spider):
        if not self.server or not self.bf:
            return item

        from jobCollection.items.boss_job_item import BossJobDetailItem
        if isinstance(item, BossJobDetailItem):
            return item

        job_id = item.get('encrypt_job_id')
        if not job_id:
            logger.warning("Item missing encrypt_job_id! Cannot deduplicate.")
            return item
        
        # Check Bloom Filter
        try:
            if self.bf.is_contains(job_id):
                spider.logger.debug(f"Duplicate job found in Bloom Filter: {job_id}")
                raise DropItem(f"Duplicate job found in Bloom Filter: {job_id}")
            else:
                # Add to Bloom Filter
                self.bf.insert(job_id)
                if not self._ttl_applied:
                    self.server.expire(self.bf_key, self.bf_ttl_seconds)
                    self._ttl_applied = True
                return item
        except redis.RedisError as e:
             logger.error(f"Redis error during Bloom Filter check: {e}")
             return item
