import asyncio
import sys
import os
from sqlalchemy import text, inspect, Integer, BigInteger
from sqlalchemy.schema import CreateTable

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from common.databases.PostgresManager import db_manager
from common.databases.models import Base

async def migrate_to_snowflake():
    print("Starting Snowflake ID migration...")
    
    # await get_session to get the actual session object
    session = await db_manager.get_session()
    async with session:
        # We need a raw connection for DDL
        conn = await session.connection()
        
        # 1. Identify Tables from Metadata
        tables = Base.metadata.tables.values()
        
        for table in tables:
            table_name = table.name
            print(f"Processing table: {table_name}")
            
            # 2. Process Columns
            for column in table.columns:
                col_name = column.name
                col_type = column.type
                
                # We only care about columns that are defined as BigInteger in the model
                # AND likely need migration from Integer in DB.
                # Since we updated models to BigInteger, we check if the model says BigInteger.
                
                if isinstance(col_type, BigInteger):
                    # Check if it's a Primary Key
                    is_pk = column.primary_key
                    
                    # Construct ALTER statement
                    # Postgres allows altering Integer -> BigInteger seamlessly
                    alter_sql = f"ALTER TABLE {table_name} ALTER COLUMN {col_name} TYPE BIGINT;"
                    try:
                        print(f"  - Converting {col_name} to BIGINT")
                        await conn.execute(text(alter_sql))
                    except Exception as e:
                        print(f"    Error altering type for {table_name}.{col_name}: {e}")

                    # If it's a PK, we likely need to drop the default (sequence)
                    # We only do this if we want to enforce application-side ID generation
                    if is_pk:
                        drop_default_sql = f"ALTER TABLE {table_name} ALTER COLUMN {col_name} DROP DEFAULT;"
                        try:
                            print(f"  - Dropping default for {col_name}")
                            await conn.execute(text(drop_default_sql))
                        except Exception as e:
                             print(f"    Error dropping default for {table_name}.{col_name}: {e}")
                             
                        # Optionally try to drop the sequence if it exists (naming convention table_col_seq)
                        seq_name = f"{table_name}_{col_name}_seq"
                        drop_seq_sql = f"DROP SEQUENCE IF EXISTS {seq_name} CASCADE;"
                        try:
                            await conn.execute(text(drop_seq_sql))
                        except Exception as e:
                             print(f"    Error dropping sequence {seq_name}: {e}")

        await session.commit()
        print("Migration completed.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(migrate_to_snowflake())
