import asyncio
import os
import sys
from dotenv import load_dotenv
from typing import List
from pydantic import BaseModel, Field

# Add project root to sys.path so we can import common modules
sys.path.append(os.getcwd())

# Load environment variables from .env
dotenv_path = os.path.join(os.getcwd(), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print(f"Loaded .env from {dotenv_path}")
else:
    print("Warning: .env not found. Please ensure AI_API_KEY is set.")

# Import LangChain components
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import PydanticOutputParser
except ImportError:
    print("Error: LangChain not installed. Please run: pip install -r requirements_agent.txt")
    sys.exit(1)

# Import Database components
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job

def get_env_cleaned(key: str, default: str = None) -> str:
    """Get env var and strip quotes if present."""
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'").strip('"')
    return val

# 1. Define the output structure (Data Model)
class JobAnalysisResult(BaseModel):
    """Result of analyzing a job description."""
    skills: List[str] = Field(description="List of technical skills and programming languages found, e.g. ['Python', 'FastAPI', 'Docker']")
    benefits: List[str] = Field(description="List of benefits and bonuses, e.g. ['Year-end bonus', 'Remote work']")
    education_requirement: str = Field(description="Education requirement if mentioned, else 'Not specified'")
    summary: str = Field(description="A brief 1-sentence summary of the job role")

async def parse_job_demo():
    print("--- 1. Connecting to Database ---")
    # Ensure DB is initialized and get session using the manager's helper
    # This automatically calls initialize() if needed and returns a session instance
    session_obj = await db_manager.get_session()
    async with session_obj as session:
        # Fetch one job that has a description
        # We eagerly load the company relationship to avoid MissingGreenlet error
        stmt = select(Job).options(selectinload(Job.company)).where(Job.description != None).limit(1)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()

        if not job:
            print("No jobs found with description in database.")
            return

        print(f"Fetched Job: {job.title} ({job.company.name if job.company else 'Unknown Co'})")
        print(f"Description length: {len(job.description)} chars")
        print("-" * 30)

        # 2. Setup LangChain
        print("\n--- 2. Setting up LangChain Agent ---")
        
        # Read from .env keys identified: AI_API_KEY, AI_BASE_URL, AI_MODEL
        api_key = get_env_cleaned("AI_API_KEY")
        base_url = get_env_cleaned("AI_BASE_URL", "https://api.openai.com/v1")
        model_name = get_env_cleaned("AI_MODEL", "gpt-3.5-turbo")
        
        print(f"Using Provider: {get_env_cleaned('AI_PROVIDER', 'unknown')}")
        print(f"Using Model: {model_name}")
        print(f"Base URL: {base_url}")
        
        if not api_key:
            print("Error: AI_API_KEY not found in environment variables.")
            return

        llm = ChatOpenAI(
            model=model_name,
            temperature=0,
            openai_api_key=api_key,
            openai_api_base=base_url
        )

        parser = PydanticOutputParser(pydantic_object=JobAnalysisResult)

        prompt = ChatPromptTemplate.from_template(
            """
            You are an expert HR and Tech Recruiter.
            Extract key information from the following job description.
            
            {format_instructions}
            
            Job Description:
            {job_desc}
            """
        )

        # Create Chain
        chain = prompt | llm | parser

        # 3. Invoke Chain
        print("\n--- 3. Invoking Agent (Parsing Description) ---")
        try:
            result = await chain.ainvoke({
                "job_desc": job.description,
                "format_instructions": parser.get_format_instructions()
            })
            
            print("\n--- Analysis Result ---")
            print(f"Summary: {result.summary}")
            print(f"Skills: {result.skills}")
            print(f"Benefits: {result.benefits}")
            print(f"Education: {result.education_requirement}")
            
        except Exception as e:
            print(f"Error during LLM processing: {e}")

if __name__ == "__main__":
    asyncio.run(parse_job_demo())
