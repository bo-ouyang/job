import os
import sys
import re
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jobCollectionWebApi.config import settings
from common.databases.models.major import Major, MajorIndustryRelation
from common.databases.models.boss_stu_crawl_url import BossStuCrawlUrl
from common.databases.models.base import Base

def parse_school_html():
    # Setup DB
    print(f"Connecting to DB: {settings.DATABASE_URL_SYNC}")
    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Read HTML
        html_path = os.path.join(current_dir, 'school.html')
        if not os.path.exists(html_path):
            print(f"Error: {html_path} not found.")
            return

        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        soup = BeautifulSoup(content, 'lxml') # Use lxml for speed if available, else html.parser
        
        # Helper to get or create Major
        def get_or_create_major(name, level, parent_id=None):
            stmt = select(Major).where(Major.name == name, Major.level == level)
            if parent_id:
                stmt = stmt.where(Major.parent_id == parent_id)
            
            existing = session.execute(stmt).scalar_one_or_none()
            if existing:
                return existing
            
            new_major = Major(name=name, level=level, parent_id=parent_id)
            session.add(new_major)
            session.flush() # Get ID
            return new_major

        # Parse 'expand-menu-list' which contains the grouped structure
        # Structure: 
        # <ul class="expand-menu-list">
        #   <li>
        #       <span class="menu-item-title">Category</span>
        #       <div class="menu-item-body"><ul><li><a href="...">Major</a></li></ul></div>
        #   </li>
        # </ul>
        
        expand_list = soup.select_one('ul.expand-menu-list')
        if not expand_list:
            print("Error: Could not find ul.expand-menu-list")
            return

        category_items = expand_list.find_all('li', recursive=False)
        print(f"Found {len(category_items)} categories.")

        total_majors = 0
        total_urls = 0

        for cat_item in category_items:
            # 1. Category
            title_span = cat_item.find('span', class_='menu-item-title')
            if not title_span:
                continue
            
            cat_name = title_span.get_text(strip=True)
            print(f"Processing Category: {cat_name}")
            
            category_obj = get_or_create_major(cat_name, 1)
            
            # 2. Sub Majors
            sub_major_links = cat_item.select('div.menu-item-body ul.menu-item-content li a')
            
            for link in sub_major_links:
                major_name = link.get_text(strip=True)
                href = link.get('href')
                ka = link.get('ka')
                
                if not major_name or not href:
                    continue
                
                # Create Major
                major_obj = get_or_create_major(major_name, 2, parent_id=category_obj.id)
                total_majors += 1

                # 3. Extract Industry Codes
                # href example: /web/geek/job?position=300403,300401...&experience=102
                parsed_url = urlparse(href)
                qs = parse_qs(parsed_url.query)
                position_str = qs.get('position', [''])[0]
                
                industry_codes = []
                if position_str:
                    industry_codes = [int(code) for code in position_str.split(',') if code.isdigit()]
                
                # Update Relation
                # Check if relation exists
                stmt_rel = select(MajorIndustryRelation).where(MajorIndustryRelation.major_id == major_obj.id)
                rel_obj = session.execute(stmt_rel).scalar_one_or_none()
                
                if not rel_obj:
                    rel_obj = MajorIndustryRelation(
                        major_id=major_obj.id,
                        major_name=major_name,
                        industry_codes=industry_codes,
                        keywords=major_name # Default keywords to major name
                    )
                    session.add(rel_obj)
                else:
                    rel_obj.industry_codes = industry_codes # Update codes
                    if not rel_obj.keywords:
                        rel_obj.keywords = major_name # Update keywords if empty
                
                # 4. Create Crawl URL
                full_url = f"https://www.zhipin.com{href}"
                
                # Check if URL exists
                stmt_url = select(BossStuCrawlUrl).where(BossStuCrawlUrl.url == full_url)
                url_obj = session.execute(stmt_url).scalar_one_or_none()
                
                if not url_obj:
                    new_url = BossStuCrawlUrl(
                        url=full_url,
                        ka=ka,
                        major_name=major_name,
                        status='pending'
                    )
                    session.add(new_url)
                    total_urls += 1
        
        session.commit()
        print(f"Done. Processed {total_majors} majors, Created {total_urls} new URLs.")

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    parse_school_html()
