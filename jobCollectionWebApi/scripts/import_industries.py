import sys
import os
import json
import asyncio
import urllib.request
import urllib.error
from sqlalchemy.dialects.postgresql import insert

import difflib

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

print(f"Script starting... Python executable: {sys.executable}", flush=True)

try:
    from common.databases.PostgresManager import db_manager
    from common.databases.models.industry import Industry
    from common.utils.snowflake import generate_id
    print("Imports successful.", flush=True)
except ImportError as e:
    print(f"Import Error: {e}", flush=True)
    # Attempt to diagnose
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f"Unexpected Error during imports: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

URL_INDUSTRY = 'https://www.zhipin.com/wapi/zpCommon/data/industry.json'
URL_POSITION = 'https://www.zhipin.com/wapi/zpCommon/data/getCityShowPosition'

def fetch_json_sync(url):
    print(f"Fetching {url}...", flush=True)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.zhipin.com/',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"  Response received from {url}", flush=True)
            data = response.read()
            return json.loads(data.decode('utf-8'))
    except Exception as e:
        print(f"Failed to fetch {url}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return None

async def import_data():
    print("In import_data()...", flush=True)
    # 1. Fetch Data
    industry_resp = fetch_json_sync(URL_INDUSTRY)
    position_resp = fetch_json_sync(URL_POSITION)
    
    if not industry_resp or not industry_resp.get('zpData'):
        print("Error: Could not fetch industry data.", flush=True)
        return
        
    if not position_resp or not position_resp.get('zpData'):
        print("Error: Could not fetch position data.", flush=True)
        return

    industry_list = industry_resp['zpData']
    
    # URL_POSITION structure is {'zpData': {'position': [...]}}
    if isinstance(position_resp['zpData'], dict) and 'position' in position_resp['zpData']:
        pos_list = position_resp['zpData']['position']
    elif isinstance(position_resp['zpData'], list):
        pos_list = position_resp['zpData']
    else:
        print("Error: Unexpected structure for position data.", flush=True)
        return

    # Map for quick lookup:  Code -> IndustryItem
    industry_map_by_code = {} 
    
    industries_to_upsert = []
    
    print("Processing industry data...", flush=True)
    # Process Industry Data (Source of Truth for Hierarchy)
    # Recursively parse URL_INDUSTRY
    def parse_industry_level(items, parent_code, level):
        for item in items:
            try:
                code = int(item['code'])
            except:
                continue
            
            p_code = int(parent_code) if parent_code is not None else None
            
            industry_data = {
                'id': generate_id(),
                'code': code,
                'name': item['name'],
                'parent_id': p_code,
                'level': level,
                'tip': item.get('tip'),
                'first_char': item.get('firstChar'),
                'pinyin': item.get('pinyin'),
                'rank': item.get('rank', 0),
                'mark': item.get('mark', 0),
                'position_type': item.get('positionType', 0),
                'city_type': item.get('cityType'),
                'capital': item.get('capital', 0),
                'color': item.get('color'),
                'recruitment_type': str(item.get('recruitmentType')) if item.get('recruitmentType') else None,
                'city_code': str(item.get('cityCode')) if item.get('cityCode') else None,
                'region_code': item.get('regionCode'),
                'center_geo': item.get('centerGeo'),
                'value': item.get('value'),
                '_source': 'industry' 
            }
            industries_to_upsert.append(industry_data)
            industry_map_by_code[code] = industry_data
            
            if item.get('subLevelModelList'):
                parse_industry_level(item['subLevelModelList'], code, level + 1)

    parse_industry_level(industry_list, None, 0)
    print(f"Loaded {len(industry_map_by_code)} nodes from URL_INDUSTRY tree.", flush=True)

    matched_root_count = 0
    new_positions_count = 0
    
    def add_position_sublevels(sub_items, parent_code, current_level, visited_codes=None):
        nonlocal new_positions_count
        if not sub_items:
            return
        
        if visited_codes is None:
            visited_codes = set()
            
        for sub in sub_items:
            try:
                sub_code = int(sub['code'])
            except:
                continue
            
            # If this position code already exists in Industry Data, we skip adding it as a new node,
            # BUT we might need to check if it has children that act as positions.
            # However, typically URL_POSITION structure mirrors industry structure then adds positions.
            # If sub_code is already in industry_map, it means it's a category, not a leaf position (usually).
            # We should recurse into it using the EXISTING industry code as parent for next level.
            
            if sub_code in industry_map_by_code:
                # Code exists. Recurse to see if there are children not in industry map
                 if sub.get('subLevelModelList'):
                     add_position_sublevels(sub['subLevelModelList'], sub_code, current_level + 1, visited_codes)
                 continue
            
            # New Position Node
            if sub_code in visited_codes: 
                continue # Prevent infinite loops if circular
            visited_codes.add(sub_code)

            sub_data = {
                'id': generate_id(),
                'code': sub_code,
                'name': sub['name'],
                'parent_id': parent_code,
                'level': current_level,
                'tip': sub.get('tip'), # ... (rest of fields same as above)
                'first_char': sub.get('firstChar'),
                'pinyin': sub.get('pinyin'),
                'rank': sub.get('rank', 0),
                'mark': sub.get('mark', 0),
                'position_type': sub.get('positionType', 0),
                'city_type': sub.get('cityType'),
                'capital': sub.get('capital', 0),
                'color': sub.get('color'),
                'recruitment_type': str(sub.get('recruitmentType')) if sub.get('recruitmentType') else None,
                'city_code': str(sub.get('cityCode')) if sub.get('cityCode') else None,
                'region_code': sub.get('regionCode'),
                'center_geo': sub.get('centerGeo'),
                'value': sub.get('value'),
                '_source': 'position'
            }
            industries_to_upsert.append(sub_data)
            new_positions_count += 1
            
            if sub.get('subLevelModelList'):
                add_position_sublevels(sub['subLevelModelList'], sub_code, current_level + 1, visited_codes)

    print("Matching position data to industry roots...", flush=True)
    # Walk URL_POSITION tree
    # For each root in URL_POSITION, find its match in Industry Data
    for pos_item in pos_list:
        matched_code = None
        
        # 1. Try Code Match
        try:
            p_code = int(pos_item['code'])
            if p_code in industry_map_by_code:
                matched_code = p_code
        except:
            pass

        # 2. Try Fuzzy Name Match
        if matched_code is None:
            best_ratio = 0
            best_match_code = None
            pos_name = pos_item['name']
            
            for ind_code, ind_item in industry_map_by_code.items():
                ind_name = ind_item['name']
                if pos_name == ind_name:
                    best_ratio = 1.0
                    best_match_code = ind_code
                    break
                if pos_name in ind_name or ind_name in pos_name:
                    ratio = 0.9 
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match_code = ind_code
                ratio = difflib.SequenceMatcher(None, pos_name, ind_name).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match_code = ind_code
            
            if best_ratio > 0.6:
                matched_code = best_match_code

        if matched_code is not None:
             matched_root_count += 1
             # Use the MATCHED Industry Code as the parent for the children of this position item
             # Also, we must determine the level. The matched item has a level. Children should be level + 1.
             matched_item = industry_map_by_code[matched_code]
             start_level = matched_item['level'] + 1
             
             if pos_item.get('subLevelModelList'):
                 add_position_sublevels(pos_item['subLevelModelList'], matched_code, start_level)
        else:
            # If root unmatched, add it as a new top-level industry/category
            print(f"Adding new root from Position Data: {pos_item['name']} ({pos_item.get('code')})", flush=True)
            
            try:
                new_root_code = int(pos_item['code'])
            except:
                continue
                
            new_root_data = {
                'id': generate_id(),
                'code': new_root_code,
                'name': pos_item['name'],
                'parent_id': None, # New root
                'level': 0,
                'tip': pos_item.get('tip'),
                'first_char': pos_item.get('firstChar'),
                'pinyin': pos_item.get('pinyin'),
                'rank': pos_item.get('rank', 0),
                'mark': pos_item.get('mark', 0),
                'position_type': pos_item.get('positionType', 0),
                'city_type': pos_item.get('cityType'),
                'capital': pos_item.get('capital', 0),
                'color': pos_item.get('color'),
                'recruitment_type': str(pos_item.get('recruitmentType')) if pos_item.get('recruitmentType') else None,
                'city_code': str(pos_item.get('cityCode')) if pos_item.get('cityCode') else None,
                'region_code': pos_item.get('regionCode'),
                'center_geo': pos_item.get('centerGeo'),
                'value': pos_item.get('value'),
                '_source': 'position_root'
            }
            industries_to_upsert.append(new_root_data)
            
            # Recurse for children
            if pos_item.get('subLevelModelList'):
                 add_position_sublevels(pos_item['subLevelModelList'], new_root_code, 1)

    print(f"Matched {matched_root_count} roots from Position Data. Added {new_positions_count} new position items.", flush=True)
    print(f"Total items to upsert: {len(industries_to_upsert)}", flush=True)

    # 3. DB Upsert
    print("Initializing DB connection...", flush=True)
    await db_manager.initialize()

    # Deduplicate
    unique_map = {}
    for item in industries_to_upsert:
        unique_map[item['code']] = item
    
    final_list = list(unique_map.values())
    
    async with db_manager.async_session() as session:
        chunk_size = 100
        total = len(final_list)
        
        # Pass 1
        pass1_list = []
        for x in final_list:
            c = x.copy()
            c.pop('_source', None)
            c['parent_id'] = None
            pass1_list.append(c)
            
        print("Pass 1: Upserting data...", flush=True)
        for i in range(0, total, chunk_size):
            chunk = pass1_list[i:i + chunk_size]
            stmt = insert(Industry).values(chunk)
            update_dict = {
                c.name: c for c in stmt.excluded if c.name not in ['id', 'code']
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=['code'],
                set_=update_dict
            )
            await session.execute(stmt)
            await session.commit()
            print(f"Pass 1: {min(i + chunk_size, total)} / {total}", flush=True)
            
        # Pass 2
        rows_with_parent = [x for x in final_list if x['parent_id'] is not None]
        total_p = len(rows_with_parent)
        print(f"Pass 2: Updating {total_p} relationships...", flush=True)
        for i in range(0, total_p, chunk_size):
            chunk = []
            for item in rows_with_parent[i:i+chunk_size]:
                c = item.copy()
                c.pop('_source', None)
                chunk.append(c)
            
            stmt = insert(Industry).values(chunk)
            update_dict = { 'parent_id': stmt.excluded.parent_id }
            stmt = stmt.on_conflict_do_update(
                index_elements=['code'],
                set_=update_dict
            )
            await session.execute(stmt)
            await session.commit()
            print(f"Pass 2: {min(i + chunk_size, total_p)} / {total_p}", flush=True)

    print("Import completed successfully.", flush=True)

if __name__ == "__main__":
    print("Entered main block.", flush=True)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    print("Starting event loop...", flush=True)
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(import_data())
    except Exception as e:
        print(f"Error in execution: {e}", flush=True)
        import traceback
        traceback.print_exc()
