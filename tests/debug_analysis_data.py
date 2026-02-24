import sys
import os
import asyncio
import logging

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from common.databases.PostgresManager import db_manager
from jobCollectionWebApi.crud.major import major as crud_major
from jobCollectionWebApi.crud.job import job as crud_job

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_analysis():
    await db_manager.initialize()
    async_session = db_manager.async_session
    
    async with async_session() as session:
        print("\n--- Testing Major Analysis Data ---")
        major_name = "计算机科学与技术" # Use a known major
        
        # 1. Get Industry Codes
        relation = await crud_major.get_relation_by_major_name(session, major_name)
        industry_codes = []
        if relation and relation.industry_codes:
            industry_codes = relation.industry_codes
            print(f"Found Industry Codes for {major_name}: {industry_codes}")
        else:
            print(f"No relation found for {major_name}")

        keywords = ["Java", "后端"]
        location = None
        
        print(f"Analyzing with keywords: {keywords}, industry_codes: {industry_codes}")

        # 2. Run Analysis
        try:
            result = await crud_job.analyze_by_keywords(
                session, 
                keywords=keywords,
                location=location,
                industry_codes=industry_codes
            )
            
            print("\n--- Analysis Result ---")
            print(f"Total Jobs: {result.get('total_jobs')}")
            print(f"Salary Data Points: {len(result.get('salary', []))}")
            print(f"Industry Data Points: {len(result.get('industries', []))}")
            print(f"Skills Data Points: {len(result.get('skills', []))}")
            
            if not result.get('industries'):
                print("!! Industry data is empty !!")
            else:
                print("Industry Sample:", result['industries'][:2])
                
            if not result.get('skills'):
                print("!! Skills data is empty !!")
            else:
                print("Skills Sample:", result['skills'][:2])
                
        except Exception as e:
            print(f"Analysis Failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(debug_analysis())
