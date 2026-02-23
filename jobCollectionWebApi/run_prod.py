import uvicorn
import os
import sys

# 生产环境启动脚本 (支持多 Worker 高并发)
# 用法: python run_prod.py

if __name__ == "__main__":
    # 获取 CPU 核心数，设置为 workers 数量 (通常建议 2*CPU + 1 或直接 CPU 数)
    # Windows 下 uvicorn 通过 spawn 启动子进程，支持 workers 参数
    cpu_count = os.cpu_count() or 1
    workers = max(4, cpu_count) # 至少4个 worker
    
    print(f"Starting server with {workers} workers...")
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        workers=workers, 
        loop="asyncio",
        log_level="debug"
    )
