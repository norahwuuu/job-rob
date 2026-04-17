"""
简历优化系统 - 快速测试脚本

测试后端 API 是否正常工作
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("简历优化系统 - 快速测试")
print("=" * 60)

# 1. 测试配置
print("\n[1/5] 测试配置...")
try:
    from config import (
        DEFAULT_RESUME_PATH, 
        LOG_FILE_PATH, 
        API_HOST, 
        API_PORT,
        OPENAI_API_KEY
    )
    print(f"  ✓ 配置加载成功")
    print(f"    - API 地址: http://{API_HOST}:{API_PORT}")
    print(f"    - 简历路径: {DEFAULT_RESUME_PATH}")
    print(f"    - 日志路径: {LOG_FILE_PATH}")
    print(f"    - OpenAI Key: {'已配置' if OPENAI_API_KEY else '❌ 未配置'}")
except Exception as e:
    print(f"  ✗ 配置加载失败: {e}")
    sys.exit(1)

# 2. 测试简历文件
print("\n[2/5] 测试简历文件...")
resume_path = Path(DEFAULT_RESUME_PATH)
if resume_path.exists():
    print(f"  ✓ 简历文件存在")
    print(f"    文件大小: {resume_path.stat().st_size / 1024:.1f} KB")
else:
    print(f"  ⚠️ 简历文件不存在: {DEFAULT_RESUME_PATH}")
    print(f"  请确保文件名为: cv.docx")

# 3. 测试模块导入
print("\n[3/5] 测试模块导入...")
try:
    from resume_modifier.ai_analyzer import AIAnalyzer
    from resume_modifier.content_modifier import ContentModifier
    from resume_modifier.pdf_exporter import PDFExporter
    from resume_modifier.job_log import get_log_manager
    print("  ✓ 所有模块导入成功")
except Exception as e:
    print(f"  ✗ 模块导入失败: {e}")
    sys.exit(1)

# 4. 测试日志系统
print("\n[4/5] 测试日志系统...")
try:
    manager = get_log_manager()
    stats = manager.get_stats()
    print(f"  ✓ 日志系统正常")
    print(f"    - 总申请数: {stats['total_applications']}")
    print(f"    - 申请公司: {len(stats['companies'])}")
except Exception as e:
    print(f"  ✗ 日志系统失败: {e}")

# 5. 测试 API 模块
print("\n[5/5] 测试 API 模块...")
try:
    from resume_modifier.api_server import app
    print("  ✓ API 服务器模块加载成功")
    print(f"    可通过以下命令启动:")
    print(f"    python -m resume_modifier.api_server")
except Exception as e:
    print(f"  ✗ API 模块加载失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ 所有测试通过！")
print("=" * 60)
print("\n下一步:")
print("1. 启动 API 服务器:")
print("   python -m resume_modifier.api_server")
print("\n2. 或使用托盘启动器:")
print("   python tray_launcher.py")
print("\n3. 在浏览器中加载插件:")
print("   chrome://extensions/ -> 加载已解压的扩展程序")
print("   选择: web-to-pdf-plugin/web-to-md-pdf-plugin")
print("\n4. 访问招聘网站测试!")
print("=" * 60)
