"""
简历自动修改程序 - 使用示例

使用前请设置环境变量:
  Windows PowerShell: $env:OPENAI_API_KEY = "sk-xxx"
  或在此文件中直接设置 API_KEY
"""

import os
import sys

# Fix encoding for Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# ============================================
# 配置区域 - 请修改以下设置
# ============================================

# OpenAI API 密钥 (也可以通过环境变量设置)
API_KEY = ""  # 在这里填入你的 API 密钥

# 简历文件路径
RESUME_PATH = "cv.docx"

# 岗位描述 - 这是你要应聘的岗位要求
JOB_DESCRIPTION = """
We are looking for an AI/ML Engineer to assess and develop novel AI-based solutions for core Rohde & Schwarz products. You will enhance and generate new product features for our customers using the best of what the constantly evolving set of AI/ML architectures, tools and models offer. The domains are diverse from computer vision, audio, through KPI and signal analysis. The fields of application are equally diverse spanning each of Rohde & Schwarz’s business domains.
Your tasks
Develop value generating capabilities with ML and (generative) AI models and techniques.
Integrate AI/ML models in Rohde & Schwarz products with massive real-time signal recordings.
Analyze data quality and performance metrics to optimize model accuracy, latency, and energy efficiency.
Collaborate with stakeholders to ensure an iterative business driven approach.
Collaborate with MLOps engineers in the transition from prototypes into production-ready deployments.
Stay up to date on emerging AI/ML research and adapt techniques to your use-cases and to be aware of opportunities which new methods may make available.
"""

# 输出目录
OUTPUT_DIR = "./output"

# ============================================
# 以下为程序执行代码
# ============================================

def main():
    # 检查 API 密钥
    if not API_KEY:
        print("=" * 60)
        print("ERROR: Please set OPENAI_API_KEY")
        print("=" * 60)
        print("\nOption 1: Set environment variable:")
        print('  PowerShell: $env:OPENAI_API_KEY = "sk-xxx"')
        print("\nOption 2: Edit this file and set API_KEY directly")
        print("=" * 60)
        return
    
    from resume_modifier.main import process_resume
    
    print("=" * 60)
    print("Resume Auto-Modifier")
    print("=" * 60)
    print(f"\nResume: {RESUME_PATH}")
    try:
        job_desc_preview = JOB_DESCRIPTION[:50] if len(JOB_DESCRIPTION) > 50 else JOB_DESCRIPTION
        print(f"Job Description: {job_desc_preview}...")
    except UnicodeEncodeError:
        print(f"Job Description: (contains non-ASCII characters, length: {len(JOB_DESCRIPTION)} chars)")
    print(f"Output: {OUTPUT_DIR}")
    print("\nProcessing...")
    
    result = process_resume(
        resume_path=RESUME_PATH,
        job_description=JOB_DESCRIPTION,
        output_dir=OUTPUT_DIR,
        output_name="tailored_resume",
        api_key=API_KEY,
        skip_pdf=False,
        verbose=True,
        debug=False  # 关闭调试模式
    )
    
    print("\n" + "=" * 60)
    if result["success"]:
        print("SUCCESS!")
        print(f"\nOutput files:")
        if result.get("word_path"):
            print(f"  Word: {result['word_path']}")
        if result.get("pdf_path"):
            print(f"  PDF:  {result['pdf_path']}")
        
        if result.get("modifications"):
            print(f"\nModifications ({len(result['modifications'])}):")
            for m in result["modifications"]:
                try:
                    target = m['target'][:30] if len(m['target']) > 30 else m['target']
                    replacement = m['replacement'][:30] if len(m['replacement']) > 30 else m['replacement']
                    print(f"  - {target}... -> {replacement}...")
                except (UnicodeEncodeError, KeyError):
                    print(f"  - Modification applied (contains non-ASCII characters)")
        
        if result.get("suggestions"):
            print(f"\nSuggestions:")
            for s in result["suggestions"]:
                try:
                    print(f"  * {s}")
                except UnicodeEncodeError:
                    print(f"  * (suggestion contains non-ASCII characters)")
        
        if result.get("match_score"):
            print(f"\nExpected match score: {result['match_score']}%")
    else:
        print(f"FAILED: {result.get('error')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
