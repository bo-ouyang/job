import asyncio
import os
import sys

# Add project root and jobCollectionWebApi to path
current_dir = os.path.dirname(os.path.abspath(__file__))
web_api_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(web_api_dir)

sys.path.append(project_root)
sys.path.append(web_api_dir)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from common.databases.PostgresManager import db_manager
from core.config import settings

async def migrate_industries():
    # Initialize the database manager
    db_manager.init(settings.SQLALCHEMY_DATABASE_URI)
    
    print("Starting industry table migration...")
    async with db_manager.async_session() as session:
        # 1. Add `path` column if it doesn't exist
        try:
            print("Adding `path` column...")
            await session.execute(text("ALTER TABLE industries ADD COLUMN IF NOT EXISTS path VARCHAR(255);"))
            await session.commit()
            
            print("Adding index on `path` column...")
            await session.execute(text("CREATE INDEX IF NOT EXISTS ix_industries_path ON industries (path);"))
            await session.commit()
            print("Column and index created successfully.")
        except Exception as e:
            print(f"Error adding column/index: {e}")
            await session.rollback()

        # 2. Re-calculate paths for all industries using a recursive CTE
        try:
            print("Calculating and updating materialized paths for all industries...")
            update_query = text("""
                WITH RECURSIVE industry_paths AS (
                    -- Base case: Root nodes
                    SELECT 
                        code, 
                        CAST(code AS VARCHAR) || '/' AS computed_path
                    FROM industries
                    WHERE parent_id IS NULL

                    UNION ALL

                    -- Recursive step: Child nodes
                    SELECT 
                        i.code, 
                        ip.computed_path || CAST(i.code AS VARCHAR) || '/' AS computed_path
                    FROM industries i
                    INNER JOIN industry_paths ip ON i.parent_id = ip.code
                )
                UPDATE industries i
                SET path = ip.computed_path
                FROM industry_paths ip
                WHERE i.code = ip.code;
            """)
            await session.execute(update_query)
            await session.commit()
            print("Path calculation and update completed successfully.")
        except Exception as e:
            print(f"Error updating paths: {e}")
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(migrate_industries())
