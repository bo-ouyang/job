import asyncio
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.databases.PostgresManager import db_manager
from services.ai_access_service import ai_access_service
from core.logger import sys_logger as logger

async def init():
    print("Connecting to DB to ensure pricing products exist...")
    async with db_manager.async_session() as session:
        res = await ai_access_service.ensure_pricing_products(session)
        print(f"Created {res} new pricing products in the database.")

if __name__ == "__main__":
    asyncio.run(init())
    print("Done.")
