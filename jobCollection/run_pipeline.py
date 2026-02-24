import subprocess
import time
import os
import sys
import psutil

# Get absolute path to the virtual env python to ensure sub-scripts use the same env
PYTHON_EXECUTABLE = sys.executable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define scripts relative to the current directory (jobCollection)
SIMPLE_SCRIPT_DIR = os.path.join(BASE_DIR, "jobCollection", "simple_script")
LIST_SPIDER_CMD = "scrapy crawl boss_list"
LIST_CONTROLLER_SCRIPT = "boss_list_gui_controller.py"

DETAIL_SPIDER_CMD = "scrapy crawl boss_detail"
DETAIL_CONTROLLER_SCRIPT = "boss_detail_gui_controller.py"

def kill_process_by_name(name):
    """Utility to ensure clean states by killing straggler processes"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
             # Check if the process matches our script name
             cmdline = proc.info.get('cmdline')
             if cmdline and name in cmdline:
                 print(f"[Pipeline] Cleaning up previous orphaned process: {name} (PID: {proc.info['pid']})")
                 proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def trigger_spider_task_in_db():
    """
    Ensure there's a pending task in SpiderBossCrawlUrl for the list spider to pick up.
    Since we are orchestrating, the user must have provided a URL beforehand or this runs perpetually.
    (This function assumes the user has already inserted a 'pending' monitor task in DB/GUI layer 
    or the monitor spider just loops waiting).
    """
    # For now, we just rely on boss_monitor_drission's internal loop
    pass

def run_list_spider():
    print("=============================================")
    print("   [STAGE 1] Starting List Spider (Monitor)  ")
    print("   Scanning pages to gather Job UUIDs...     ")
    print("=============================================")
    
    # 1. Ensure any old ones are dead
    # Cannot easily kill by name for generic scrapy processes, but we can try
    kill_process_by_name("boss_list")
    kill_process_by_name(LIST_CONTROLLER_SCRIPT)

    # 1.5 Launch the List GUI Controller
    print(f"[Pipeline] Launching List GUI Controller: {LIST_CONTROLLER_SCRIPT}")
    list_gui_process = subprocess.Popen(
        [PYTHON_EXECUTABLE, LIST_CONTROLLER_SCRIPT], 
        cwd=SIMPLE_SCRIPT_DIR
    )
    time.sleep(2) # Give GUI controller time to boot
    
    # 2. Launch the List Spider (Scrapy via subprocess)
    print(f"[Pipeline] Launching List Spider Process: {LIST_SPIDER_CMD}")
    list_process = subprocess.Popen(LIST_SPIDER_CMD.split(), shell=True, cwd=BASE_DIR)
    
    # Wait for the task to be marked as 'done'
    print("[Pipeline] Waiting for List Spider to complete all jobs...")
    try:
        while True:
            # Poll every 5 seconds
            time.sleep(5)
            
            # Scrapy processes terminate when the crawler finishes emitting/listening hooks
            if list_process.poll() is not None:
                if list_process.returncode != 0:
                     print(f"[Pipeline] List Spider Process exited unexpectedly with code {list_process.returncode}")
                else:
                     print(f"[Pipeline] List Spider completed its crawl successfully!")
                break
                
    except KeyboardInterrupt:
        list_process.terminate()
        try:
            list_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            list_process.kill()
        
        if list_gui_process.poll() is None:
             list_gui_process.terminate()
        sys.exit(0)

    # Gracefully Stop the List Spider so we transition
    if list_process.poll() is None:
        print("[Pipeline] Tearing down List Spider Process...")
        list_process.terminate()
        try:
            list_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            list_process.kill()
            
    if list_gui_process.poll() is None:
        print("[Pipeline] Tearing down List GUI Controller...")
        list_gui_process.terminate()
        try:
            list_gui_process.wait(timeout=5)
        except:
             list_gui_process.kill()
             
    print("[Pipeline] >>> Stage 1 Completed <<<\n")


def run_detail_spider():
    print("=============================================")
    print("   [STAGE 2] Starting Detail Spider Workers  ")
    print("   Filling details for all is_crawl=0 DB rows")
    print("=============================================")
    
    # 1. Clean up old orphan GUI controllers
    kill_process_by_name(DETAIL_CONTROLLER_SCRIPT)
    
    # 2. Launch GUI Controller (Background)
    print(f"[Pipeline] Launching Detail GUI Controller: {DETAIL_CONTROLLER_SCRIPT}")
    gui_controller = subprocess.Popen(
        [PYTHON_EXECUTABLE, DETAIL_CONTROLLER_SCRIPT], 
        cwd=SIMPLE_SCRIPT_DIR
    )
    
    # Give it a second to connect to Redis
    time.sleep(2)
    
    # 3. Launch the Scrapy Detail Process
    print(f"[Pipeline] Launching Scrapy Detail Spider: {DETAIL_SPIDER_CMD}")
    try:
        # We run the scrapy command as an executable blocking call
        # It will automatically exit when there are no more is_crawl=0 jobs to process!
        # Because we yield from DB and Stop on Idle (Wait, actually BossBaseSpider has Idle loop...)
        # Wait, the BossBaseSpider `spider_idle` currently prevents it from closing (DontCloseSpider),
        # as it continuously pings Redis. You might need to Ctrl+C it manually, 
        # OR we just let it run perpetually as a final resting state.
        
        scrapy_args = DETAIL_SPIDER_CMD.split()
        # Ensure it runs globally in jobCollection where scrapy.cfg is
        scrapy_process = subprocess.Popen(scrapy_args, shell=True, cwd=BASE_DIR)
        
        scrapy_process.wait() # Wait until user stops it (since detail runs infinitely looking for DB)
        
    except KeyboardInterrupt:
         print("\n[Pipeline] Interrupted by user during Detail Phase. Shutting down Workers...")
    finally:
         if gui_controller.poll() is None:
              gui_controller.terminate()
              try:
                  gui_controller.wait(5)
              except:
                  gui_controller.kill()
         if scrapy_process and scrapy_process.poll() is None:
              scrapy_process.terminate()

def run():
    print("=========================================================")
    print("   Boss Total Automation Orchestrator (The Pipeline)     ")
    print("   1. Automatically runs Job List Extraction             ")
    print("   2. Transitions to UI Automation Detail Extraction      ")
    print("=========================================================\n")
    
    run_list_spider()
    run_detail_spider()
    
    print("\n[Pipeline] All Stages fully executed.")

if __name__ == "__main__":
    run()
