import os
import sys

# Add project root to sys.path
sys.path.append(os.getcwd())

from jobCollectionWebApi.core.celery_app import celery_app

def trigger_batch_test():
    print(">>> (测试) 开始发送打点信号至 Celery 从而主动触发批量处理 Job Task...")
    # Celery 接收的参数签名为 process_job_parsing_task() 不需要外加 args
    celery_app.send_task("jobCollectionWebApi.tasks.job_parser.process_job_parsing_task")
    print("触发信号成功投递，请在运行中的 Celery Worker 控制台查看是否有查询并处理未分析数据库 Job 的进展日志。")

if __name__ == "__main__":
    trigger_batch_test()
