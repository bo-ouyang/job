import asyncio
import sys
import os
import aiohttp

# Add project root to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
sys.path.append(current_dir)

from services.auth_service import auth_service
from common.databases.PostgresManager import db_manager
from schemas.token import LoginRequest, PhoneLoginRequest

BASE_URL = "http://localhost:8000/api/v1/auth"

async def test_auth_flows():
    print("Initializing DB...")
    await db_manager.initialize()
    
    # Needs running server for HTTP tests if we use requests, 
    # but here we can test service logic directly or mock valid HTTP calls.
    # Let's test service logic directly to avoid server dependency if possible,
    # OR better: run against the running server if user has it up.
    # User has server running (PID 21072 stopped? No, user restarted logic is implied).
    # Step 1210 logs show "python .\main.py (running for 17m51s)".
    # So we can hit localhost:8000 through aiohttp.
    
    async with aiohttp.ClientSession() as session:
        print("\n--- Test 1: Phone Verification & Login ---")
        phone = "13800000000"
        
        # 1. Send SMS (Mock)
        async with session.post(f"{BASE_URL}/send-sms", json={"phone": phone, "type": "login"}) as resp:
            data = await resp.json()
            print(f"Send SMS Response: {resp.status} {data}")
            if "debug_code" in data:
                code = data["debug_code"]
            else:
                # If not debug, we can't automate easily without mocking.
                # Assuming DEBUG is likely True in dev.
                print("Cannot get code automatically (DEBUG=False?)")
                return

        # 2. Login with Phone
        print(f"Logging in with code: {code}")
        async with session.post(f"{BASE_URL}/login/phone", json={"phone": phone, "verification_code": code}) as resp:
            data = await resp.json()
            print(f"Login Response: {resp.status}")
            if resp.status == 200:
                print("Login Success!")
                token = data["token"]["access_token"]
                refresh = data["token"]["refresh_token"]
            else:
                print(f"Login Failed: {data}")
                return

        print("\n--- Test 2: Refresh Token ---")
        async with session.post(f"{BASE_URL}/refresh-token", json={"refresh_token": refresh}) as resp:
            data = await resp.json()
            print(f"Refresh Response: {resp.status}")
            if resp.status == 200:
                print("Refresh Success!")
                print(f"New Token: {data['access_token'][:20]}...")
            else:
                print(f"Refresh Failed: {data}")

        print("\n--- Test 3: WeChat Scan (Mock) ---")
        # 1. Generate Ticket
        async with session.get(f"{BASE_URL}/qrcode/generate") as resp:
            data = await resp.json()
            ticket = data["ticket"]
            print(f"Ticket Generated: {ticket}")

        # 2. Simulate Scan
        async with session.post(f"{BASE_URL}/qrcode/dev/scan?ticket={ticket}") as resp:
            print(f"Scan Status: {resp.status}")

        # 3. Simulate Confirm
        async with session.post(f"{BASE_URL}/qrcode/dev/confirm?ticket={ticket}") as resp:
            print(f"Confirm Status: {resp.status}")
            
        # 4. Check Status
        async with session.get(f"{BASE_URL}/qrcode/status?ticket={ticket}") as resp:
            data = await resp.json()
            print(f"Final Status: {data.get('status')}")
            if data.get('status') == 'confirmed':
                print("WeChat Login Confirmed!")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_auth_flows())
