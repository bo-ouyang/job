import sys
import os
import asyncio

# Add project root to path
# Assuming verify_major_analysis.py is at d:\Code\job\tests\verify_major_analysis.py
# Project root is d:\Code\job
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Adjust relative imports if not running as module
# We can use absolute imports since we added project_root to sys.path

from common.databases.PostgresManager import db_manager
from jobCollectionWebApi.crud.major import major as crud_major # Absolute import
from common.databases.models.major import Major, MajorIndustryRelation
from sqlalchemy import select, update

async def verify():
    print(f"Connecting to DB...")
    await db_manager.initialize()
    
    # Use context manager for session
    async with db_manager.async_session() as session:
        print("\n--- 1. Verify Major Presets (Categories + Children) ---")
        categories = await crud_major.get_categories_with_children(session)
        print(f"Found {len(categories)} categories.")
        
        has_children = False
        for cat in categories:
            print(f"  Category: {cat.name} (Level {cat.level}) - Children: {len(cat.children)}")
            if cat.children:
                has_children = True
                print(f"    Sample Child: {cat.children[0].name} (Level {cat.children[0].level})")
        
        if not has_children:
            print("WARNING: No children found for categories. Data population issue?")

        print("\n--- 2. Verify Hot Index Increment ---")
        # Find a relation to test
        stmt = select(MajorIndustryRelation).limit(1)
        result = await session.execute(stmt)
        relation = result.scalar_one_or_none()
        
        if relation:
            major_name = relation.major_name
            initial_score = relation.relevance_score or 0
            print(f"Testing Major: {major_name}, Initial Score: {initial_score}")
            print(f"Industry Codes: {relation.industry_codes}")

            # Test increment function
            success = await crud_major.increment_hot_index(session, major_name=major_name)
            if success:
                print("Increment function returned True.")
                
                # Check DB value
                # Create NEW session to ensure we read committed data (although same session should see it if flushed)
                # But here we are in same transaction.
                await session.commit() 
                
                # Re-fetch
                stmt_check = select(MajorIndustryRelation).where(MajorIndustryRelation.major_name == major_name)
                res_check = await session.execute(stmt_check)
                updated_rel = res_check.scalar_one()
                print(f"Updated Score: {updated_rel.relevance_score}")
                
                if updated_rel.relevance_score == initial_score + 1:
                    print("SUCCESS: Hot index incremented correctly.")
                else:
                    print(f"FAILURE: Score mismatch. Expected {initial_score+1}, got {updated_rel.relevance_score}")
            else:
                print("FAILURE: Increment function returned False.")
        else:
            print("WARNING: No MajorIndustryRelation found. Skipping Hot Index test.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(verify())
