"""
配置文件 - API 密钥和默认设置
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# AI 提供商选择: 固定仅使用中转 OpenAI 兼容接口
AI_PROVIDER = "openai"

# OpenAI 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gemini-2.5-flash")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or os.getenv("AI_SERVER_URL") or None  # 可选：自定义 API 端点

# 输出配置
DEFAULT_OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")
OUTPUT_DIR = Path(DEFAULT_OUTPUT_DIR)

# 默认简历路径 - 预设固定简历文件
DEFAULT_RESUME_PATH = os.getenv(
    "DEFAULT_RESUME_PATH", 
    r"./cv.docx"
)

# 日志文件路径
LOG_FILE_PATH = os.getenv(
    "LOG_FILE_PATH",
    str(OUTPUT_DIR / "application_logs.json")
)

# API 服务配置
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
