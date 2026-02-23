import sys
import os
import asyncio
import logging
from sqlalchemy import select, and_

# Add project root to sys.path to ensure imports work
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from common.databases.MysqlManager import db_manager
from common.databases.models.city import City
from common.databases.models.industry import Industry
from common.databases.models.spider_boss_crawl_url import SpiderBossCrawlUrl
# Import other models to ensure SQLAlchemy registry is populated and relationships resolve
from common.databases.models.user import User
from common.databases.models.payment import PaymentOrder
from common.databases.models.wallet import UserWallet
from common.databases.models.product import Product
from common.databases.models.resume import Resume

async def generate_urls():
    """
    Generate crawler URLs for Boss Zhipin based on City and Industry data.
    """
    await db_manager.initialize()
    
    session_generator = db_manager.get_db()
    session = await session_generator.__anext__()
    
    try:
        # 1. Fetch Target Cities
        # Boss Zhipin usually uses city codes like 101010100 (Beijing).
        # We assume level=1 are the main cities we want, or specific logic if needed.
        # Check specific cities if needed, for now let's take a safe subset or all cities with correct code format.
        # Assuming `city_code` or `code` is the Boss Zhipin code. Model says `code`.
        # Taking 'level=1' which usually means major cities in hierarchy if 0 is province.
        # Let's adjust based on observing data later if needed. For now, take all cities that look valid (not provinces if they have a type)
        stmt_cities = select(City).where(City.level == 1,and_(City.rank.in_([1,2,3,4,5]) )) # Assuming level 1 are cities
        result_cities = await session.execute(stmt_cities)
        cities = result_cities.scalars().all()
        
        if not cities:
            # Fallback: maybe level definition is different, try fetch top 5 for test if empty
            logger.warning("No cities found with level=1 rank.in_([1,2,3,4,5] , fetching top 10 cities for test...")
            stmt_cities = select(City).limit(10)
            result_cities = await session.execute(stmt_cities)
            cities = result_cities.scalars().all()

        logger.info(f"Fetched {len(cities)} cities.")

        # 2. Fetch Industries
        # User requested level=1 for industries as well
        stmt_industries = select(Industry).where(Industry.level == 1)
        result_industries = await session.execute(stmt_industries)
        industries = result_industries.scalars().all()
        
        logger.info(f"Fetched {len(industries)} industries.")
        
        count_new = 0
        count_exist = 0
        
        # 3. Generate and Insert URLs
        # Limit the scope for testing? Maybe start small.
        # User said: url = https://www.zhipin.com/web/geek/jobs?city=101010100&industry=100020
        
        for city in cities:
            for industry in industries:
                # Construct URL
                # Ensure we use the correct code field. `code` seems to be the one.
                url = f"https://www.zhipin.com/web/geek/jobs?city={city.code}&industry={industry.code}"
                
                # Check exist
                stmt_check = select(SpiderBossCrawlUrl).where(SpiderBossCrawlUrl.url == url)
                result_check = await session.execute(stmt_check)
                exists = result_check.scalar_one_or_none()
                
                if not exists:
                    new_task = SpiderBossCrawlUrl(
                        url=url,
                        city_code=city.code,
                        industry_code=industry.code,
                        status="pending"
                    )
                    session.add(new_task)
                    count_new += 1
                else:
                    count_exist += 1
                    
            # Commit periodically or after each city to save memory if list is huge
            await session.commit()
            logger.info(f"Processed city {city.name}: Added {count_new} new URLs so far.")

        logger.info(f"Generation Complete. Total New: {count_new}, Existed: {count_exist}")
        
    except Exception as e:
        logger.error(f"Error generating URLs: {e}")
        await session.rollback()
    finally:
        await session.close()
        await db_manager.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(generate_urls())
