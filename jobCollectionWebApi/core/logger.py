import logging
import sys
import os
from loguru import logger

# 拦截标准库日志并转发给 Loguru 的拦截器
class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        # 尝试获取对应等级的 Loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 获取调用日志的栈深度以获取正确的文件行号
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logger(log_dir: str = "logs"):
    """
    配置全盘接管和滚动的 Loguru 日志机器
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 1. 清除所有的旧版 Loguru (例如默认的 sys.stderr 控制台输出)
    logger.remove()

    # 2. 定义统一且友好的格式 (Console)
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # 3. 重新向终端绑定高亮彩色打印
    logger.add(sys.stdout, format=console_format, level="INFO", enqueue=True)

    # 4. 绑定硬盘存留: general app log
    logger.add(
        os.path.join(log_dir, "app_{time:YYYY-MM-DD}.log"),
        format=console_format,
        level="INFO",
        rotation="00:00", # 每天午夜切割
        retention="30 days", # 最长保留30天
        enqueue=True, # 异步多线程写入保护
        backtrace=False, # 常规日志不用全栈追踪
        diagnose=False,
        encoding="utf-8"
    )

    # 5. 绑定硬盘存留: dedicated error log
    logger.add(
        os.path.join(log_dir, "error_{time:YYYY-MM-DD}.log"),
        format=console_format,
        level="ERROR",
        rotation="00:00",
        retention="30 days",
        enqueue=True,
        backtrace=True, # 错误日志开启堆栈结构回放
        diagnose=True, # 显示导致崩溃时的变量取值
        encoding="utf-8"
    )

    # 6. 接管所有使用标准库的日志体系 (尤其是 Uvicorn 和 FastAPI 内置)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # 强制让常见的自带库也流入 Loguru
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False # 防止它自己打印两次

    return logger

# 向外界暴露出全局初始化并备好的日志句柄
sys_logger = setup_logger()
