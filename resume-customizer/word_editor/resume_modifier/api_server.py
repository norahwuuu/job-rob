"""
FastAPI 服务 - 供浏览器插件调用

启动方式:
    python -m resume_modifier.api_server
    或
    uvicorn resume_modifier.api_server:app --reload
"""

import os
import re
import uuid
import shutil
import asyncio
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import API_HOST, API_PORT, DEFAULT_OUTPUT_DIR, DEFAULT_RESUME_PATH, LOG_FILE_PATH
from resume_modifier.main import process_resume
from resume_modifier.ai_analyzer import AIAnalyzer
from resume_modifier.job_log import (
    save_application_log, 
    get_log_manager, 
    ApplicationLog, 
    ModificationRecord
)


# 临时文件目录
TEMP_DIR = Path(DEFAULT_OUTPUT_DIR) / "temp"
OUTPUT_DIR = Path(DEFAULT_OUTPUT_DIR) / "results"

# 全局任务状态存储（内存态，服务重启后会丢失）
task_status: Dict[str, dict] = {}  # task_id -> {status, progress, result, error}
task_results: Dict[str, dict] = {}  # task_id -> result

# 线程池用于并行处理
executor = ThreadPoolExecutor(max_workers=3)  # 最多3个并发任务


def sanitize_filename(name: str) -> str:
    """
    清理文件名，移除不安全字符
    
    Args:
        name: 原始文件名
        
    Returns:
        安全的文件名
    """
    # 移除文件系统不允许的字符
    unsafe_chars = r'[/\\:*?"<>|]'
    safe_name = re.sub(unsafe_chars, '_', name)
    # 移除多余空格
    safe_name = re.sub(r'\s+', ' ', safe_name).strip()
    # 截断过长的名称
    if len(safe_name) > 50:
        safe_name = safe_name[:50]
    return safe_name or "Unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时创建目录
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    # 关闭时可以清理临时文件（可选）


app = FastAPI(
    title="简历自动修改 API",
    description="基于 AI 分析岗位要求，智能优化简历并导出 Word/PDF。支持浏览器插件一键优化。",
    version="2.0.0",
    lifespan=lifespan
)

# CORS 配置 - 允许浏览器插件调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源（浏览器插件需要）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ModificationDetail(BaseModel):
    """单条修改详情"""
    target: str
    replacement: str
    reason: str
    success: bool
    error_message: Optional[str] = None
    location: Optional[str] = None


class ModifyResponse(BaseModel):
    """修改响应"""
    success: bool
    task_id: str
    company_name: str = "Unknown Company"
    job_title: str = "Unknown Position"
    word_url: Optional[str] = None
    pdf_url: Optional[str] = None
    word_filename: Optional[str] = None
    pdf_filename: Optional[str] = None
    job_summary: Optional[str] = None
    match_score: Optional[int] = None
    modifications: List[ModificationDetail] = []
    success_count: int = 0
    total_count: int = 0
    suggestions: List[str] = []
    error: Optional[str] = None


class LogEntry(BaseModel):
    """日志条目"""
    timestamp: str
    company_name: str
    job_title: str
    source_url: str
    match_score: int
    success_count: int
    total_count: int


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str  # 'pending', 'processing', 'completed', 'error'
    progress: Optional[str] = None  # 进度描述
    result: Optional[dict] = None  # 完成后的结果 (ModifyResponse 或 QAResponse)
    error: Optional[str] = None


class QAQuestion(BaseModel):
    """问答条目"""
    question: str
    answer: str


class QAResponse(BaseModel):
    """问答响应"""
    success: bool
    task_id: str
    questions: List[QAQuestion] = []
    error: Optional[str] = None


class LogsResponse(BaseModel):
    """日志列表响应"""
    total: int
    logs: List[dict]


# 存储任务结果
task_results = {}


def cleanup_old_files(max_age_hours: int = 24):
    """清理过期文件"""
    now = datetime.now()
    for folder in [TEMP_DIR, OUTPUT_DIR]:
        if folder.exists():
            for item in folder.iterdir():
                if item.is_dir():
                    # 检查目录中的文件
                    try:
                        age = (now - datetime.fromtimestamp(item.stat().st_mtime)).total_seconds() / 3600
                        if age > max_age_hours:
                            shutil.rmtree(item)
                    except Exception:
                        pass
                elif item.is_file():
                    age = (now - datetime.fromtimestamp(item.stat().st_mtime)).total_seconds() / 3600
                    if age > max_age_hours:
                        item.unlink()


def process_resume_task(task_id: str, resume_path: str, job_description: str, 
                        output_dir: str, api_key: Optional[str], skip_pdf: bool,
                        source_url: str):
    """
    后台任务：处理简历
    在独立线程中运行，不阻塞主请求
    """
    try:
        # 更新状态为处理中
        task_status[task_id] = {
            'status': 'processing',
            'progress': '正在分析岗位描述...',
            'result': None,
            'error': None
        }
        
        print(f"\n{'='*70}", flush=True)
        print(f"🚀 [任务 {task_id}] 开始处理", flush=True)
        print(f"{'='*70}\n", flush=True)
        
        # 调用主流程（同步函数，运行在线程池线程中）
        result = process_resume(
            resume_path=resume_path,
            job_description=job_description,
            output_dir=output_dir,
            output_name="resume",
            api_key=api_key,
            skip_pdf=skip_pdf,
            verbose=True
        )
        
        if not result.get("success", False):
            raise Exception(result.get("error", "处理失败"))
        
        # 获取公司名和岗位名
        company_name = result.get("company_name", "Unknown Company")
        job_title = result.get("job_title", "Unknown Position")
        
        # 生成安全文件名：避免特殊字符导致下载或跨平台路径问题
        safe_company = sanitize_filename(company_name)
        safe_job = sanitize_filename(job_title)
        
        final_word_filename = f"Candidate_Resume_{safe_company}_{safe_job}.docx"
        final_pdf_filename = f"Candidate_Resume_{safe_company}_{safe_job}.pdf"
        final_cover_filename = f"Candidate_Resume_{safe_company}_{safe_job}_cover_letter.txt"
        
        task_output_dir = Path(output_dir)
        
        # 重命名文件
        word_url = None
        if result.get("word_path"):
            old_word_path = Path(result["word_path"])
            new_word_path = task_output_dir / final_word_filename
            if old_word_path.exists():
                old_word_path.rename(new_word_path)
                result["word_path"] = str(new_word_path)
                word_url = f"/api/download/{task_id}/{final_word_filename}"
        
        pdf_url = None
        if result.get("pdf_path"):
            old_pdf_path = Path(result["pdf_path"])
            new_pdf_path = task_output_dir / final_pdf_filename
            if old_pdf_path.exists():
                old_pdf_path.rename(new_pdf_path)
                result["pdf_path"] = str(new_pdf_path)
                pdf_url = f"/api/download/{task_id}/{final_pdf_filename}"

        if result.get("cover_letter_path"):
            old_cl = Path(result["cover_letter_path"])
            new_cl = task_output_dir / final_cover_filename
            if old_cl.exists():
                old_cl.rename(new_cl)
                result["cover_letter_path"] = str(new_cl)
        
        # 构建前端可直接展示的响应对象（含每条修改成功/失败）
        modifications = [
            ModificationDetail(
                target=m.get("target", ""),
                replacement=m.get("replacement", ""),
                reason=m.get("reason", ""),
                success=m.get("success", False),
                error_message=m.get("error_message"),
                location=m.get("location")
            )
            for m in result.get("modifications", [])
        ]
        
        success_count = sum(1 for m in modifications if m.success)
        
        response = ModifyResponse(
            success=True,
            task_id=task_id,
            company_name=company_name,
            job_title=job_title,
            word_url=word_url,
            pdf_url=pdf_url,
            word_filename=final_word_filename if word_url else None,
            pdf_filename=final_pdf_filename if pdf_url else None,
            job_summary=result.get("job_summary"),
            match_score=result.get("match_score"),
            modifications=modifications,
            success_count=success_count,
            total_count=len(modifications),
            suggestions=result.get("suggestions", [])
        )
        
        # 更新状态为完成
        task_status[task_id] = {
            'status': 'completed',
            'progress': '处理完成',
            'result': response.model_dump(),
            'error': None
        }
        
        # 保存结果
        task_results[task_id] = response.model_dump()
        
        # 保存日志
        try:
            save_application_log(
                company_name=company_name,
                job_title=job_title,
                source_url=source_url,
                job_summary=result.get("job_summary", ""),
                match_score=result.get("match_score", 0),
                modifications=[m.model_dump() for m in modifications],
                task_id=task_id,
                word_path=result.get("word_path"),
                pdf_path=result.get("pdf_path"),
                word_filename=final_word_filename if word_url else None,
                pdf_filename=final_pdf_filename if pdf_url else None,
                suggestions=result.get("suggestions", [])
            )
        except Exception as e:
            print(f"[Warning] 保存日志失败: {e}", flush=True)
        
        print(f"\n✅ [任务 {task_id}] 处理完成\n", flush=True)
        
    except Exception as e:
        print(f"\n❌ [任务 {task_id}] 处理失败: {str(e)}\n", flush=True)
        task_status[task_id] = {
            'status': 'error',
            'progress': None,
            'result': None,
            'error': str(e)
        }


@app.post("/api/modify-resume", response_model=TaskStatusResponse)
async def modify_resume(
    background_tasks: BackgroundTasks,
    job_description: str = Form(..., description="岗位描述文本"),
    source_url: str = Form("", description="来源网页URL"),
    skip_pdf: bool = Form(False, description="是否跳过 PDF 生成"),
    api_key: Optional[str] = Form(None, description="OpenAI API 密钥（可选）"),
    resume: Optional[UploadFile] = File(None, description="简历 Word 文档（可选，默认使用预设简历）")
):
    """
    修改简历（浏览器插件专用端点）
    
    使用预设的简历文件，根据岗位描述自动优化并生成 Word 和 PDF 文件。
    
    - **job_description**: 岗位描述文本（从网页提取）
    - **source_url**: 来源网页URL（用于日志记录）
    - **skip_pdf**: 是否跳过 PDF 生成
    - **api_key**: OpenAI API 密钥（如果未在服务器配置）
    - **resume**: 可选的简历文件，不提供则使用预设简历
    """
    # 确定使用的简历路径
    resume_path = None
    temp_path = None
    
    if resume and resume.filename:
        # 使用上传的简历
        if not resume.filename.endswith('.docx'):
            raise HTTPException(
                status_code=400,
                detail="请上传 .docx 格式的 Word 文档"
            )
        task_id = str(uuid.uuid4())[:8]
        temp_path = TEMP_DIR / f"{task_id}_{resume.filename}"
        try:
            with open(temp_path, "wb") as f:
                content = await resume.read()
                f.write(content)
            resume_path = str(temp_path)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"保存上传文件失败: {str(e)}"
            )
    else:
        # 使用预设简历
        resume_path = DEFAULT_RESUME_PATH
        if not Path(resume_path).exists():
            raise HTTPException(
                status_code=500,
                detail=f"预设简历文件不存在: {resume_path}"
            )
    
    # 生成任务 ID
    task_id = str(uuid.uuid4())[:8]
    
    # 设置输出目录
    task_output_dir = OUTPUT_DIR / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 初始化任务状态
    task_status[task_id] = {
        'status': 'pending',
        'progress': '任务已创建，等待处理...',
        'result': None,
        'error': None
    }
    
    # 提交到线程池异步处理：接口立即返回 task_id，前端通过轮询拿结果
    executor.submit(
        process_resume_task,
        task_id=task_id,
        resume_path=resume_path,
        job_description=job_description,
        output_dir=str(task_output_dir),
        api_key=api_key,
        skip_pdf=skip_pdf,
        source_url=source_url
    )
    
    # 添加清理任务（如果有临时文件）
    if temp_path:
        background_tasks.add_task(lambda: temp_path.unlink(missing_ok=True) if temp_path.exists() else None)
    
    background_tasks.add_task(cleanup_old_files)
    
    # 立即返回任务状态
    return TaskStatusResponse(
        task_id=task_id,
        status='pending',
        progress='任务已提交，正在排队...'
    )


@app.get("/api/task-status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    查询任务状态
    
    - **task_id**: 任务 ID
    """
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    status_data = task_status[task_id]
    
    response = TaskStatusResponse(
        task_id=task_id,
        status=status_data['status'],
        progress=status_data.get('progress'),
        error=status_data.get('error')
    )
    
    # 仅在完成态附带 result，处理中只返回状态与进度
    if status_data['status'] == 'completed' and status_data.get('result'):
        response.result = status_data['result']
    
    return response


@app.get("/api/download/{task_id}/{filename}")
async def download_file(task_id: str, filename: str):
    """
    下载生成的文件
    
    - **task_id**: 任务 ID
    - **filename**: 文件名
    """
    file_path = OUTPUT_DIR / task_id / filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="文件不存在或已过期"
        )
    
    # 确定 MIME 类型
    if filename.endswith('.docx'):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif filename.endswith('.pdf'):
        media_type = "application/pdf"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type
    )


@app.get("/api/task/{task_id}")
async def get_task_result(task_id: str):
    """
    获取任务结果
    
    - **task_id**: 任务 ID
    """
    if task_id not in task_results:
        raise HTTPException(
            status_code=404,
            detail="任务不存在"
        )
    
    return task_results[task_id]


@app.get("/api/logs", response_model=LogsResponse)
async def get_logs(
    limit: Optional[int] = Query(None, description="返回最近N条记录"),
    company: Optional[str] = Query(None, description="按公司名筛选")
):
    """
    获取申请日志
    
    - **limit**: 返回最近N条记录
    - **company**: 按公司名筛选（模糊匹配）
    """
    manager = get_log_manager()
    
    if company:
        logs = manager.get_logs_by_company(company)
    else:
        logs = manager.get_logs(limit=limit)
    
    return LogsResponse(
        total=len(logs),
        logs=logs
    )


@app.get("/api/logs/stats")
async def get_log_stats():
    """获取日志统计信息"""
    manager = get_log_manager()
    return manager.get_stats()


def process_qa_task(task_id: str, page_text: str, resume_path: str, source_url: str):
    """
    后台任务：处理 AI 问答
    在独立线程中运行，不阻塞主请求
    """
    try:
        # 更新状态为处理中
        task_status[task_id] = {
            'status': 'processing',
            'progress': '正在分析页面内容...',
            'result': None,
            'error': None
        }
        
        print(f"\n{'='*70}", flush=True)
        print(f"💬 [QA 任务 {task_id}] 开始处理", flush=True)
        print(f"{'='*70}\n", flush=True)
        
        # 读取简历内容
        from resume_modifier.resume_parser import ResumeParser
        parser = ResumeParser(resume_path)
        parsed_resume = parser.parse()
        resume_text = parsed_resume.full_text
        
        task_status[task_id]['progress'] = '正在提取问题并生成答案...'
        
        # 调用 AI 分析器
        analyzer = AIAnalyzer()
        qa_result = analyzer.answer_application_questions(page_text, resume_text)
        
        # 构建响应
        response = {
            'success': True,
            'task_id': task_id,
            'questions': [{'question': q['question'], 'answer': q['answer']} for q in qa_result]
        }
        
        # 更新状态为完成
        task_status[task_id] = {
            'status': 'completed',
            'progress': '处理完成',
            'result': response,
            'error': None
        }
        
        # 保存结果
        task_results[task_id] = response
        
        print(f"\n✅ [QA 任务 {task_id}] 处理完成，生成 {len(qa_result)} 个问答\n", flush=True)
        
    except Exception as e:
        print(f"\n❌ [QA 任务 {task_id}] 处理失败: {str(e)}\n", flush=True)
        task_status[task_id] = {
            'status': 'error',
            'progress': None,
            'result': None,
            'error': str(e)
        }


@app.post("/api/answer-questions", response_model=TaskStatusResponse)
async def answer_questions(
    background_tasks: BackgroundTasks,
    page_text: str = Form(..., description="页面文本内容"),
    source_url: str = Form("", description="来源网页URL"),
):
    """
    AI 问答助手（浏览器插件专用端点）
    
    从页面内容中提取申请问题，结合简历生成个性化答案。
    
    - **page_text**: 页面文本内容（从网页提取）
    - **source_url**: 来源网页URL（用于日志记录）
    """
    # 使用预设简历
    resume_path = DEFAULT_RESUME_PATH
    if not Path(resume_path).exists():
        raise HTTPException(
            status_code=500,
            detail=f"预设简历文件不存在: {resume_path}"
        )
    
    # 生成任务 ID
    task_id = str(uuid.uuid4())[:8]
    
    # 初始化任务状态
    task_status[task_id] = {
        'status': 'pending',
        'progress': '任务已创建，等待处理...',
        'result': None,
        'error': None
    }
    
    # 提交到线程池异步处理
    executor.submit(
        process_qa_task,
        task_id=task_id,
        page_text=page_text,
        resume_path=resume_path,
        source_url=source_url
    )
    
    background_tasks.add_task(cleanup_old_files)
    
    # 立即返回任务状态
    return TaskStatusResponse(
        task_id=task_id,
        status='pending',
        progress='任务已提交，正在排队...'
    )


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok", 
        "timestamp": datetime.now().isoformat(),
        "default_resume": DEFAULT_RESUME_PATH,
        "resume_exists": Path(DEFAULT_RESUME_PATH).exists()
    }


@app.get("/")
async def root():
    """API 根路径"""
    return {
        "name": "简历自动修改 API",
        "version": "2.0.0",
        "docs": "/docs",
        "endpoints": {
            "modify": "POST /api/modify-resume",
            "download": "GET /api/download/{task_id}/{filename}",
            "task": "GET /api/task/{task_id}",
            "logs": "GET /api/logs",
            "logs_stats": "GET /api/logs/stats",
            "health": "GET /api/health"
        }
    }


def start_server(host: str = None, port: int = None):
    """启动服务器"""
    import uvicorn
    
    host = host or API_HOST
    port = port or API_PORT
    
    print(f"=" * 50)
    print(f"简历自动修改 API 服务 v2.0.0")
    print(f"=" * 50)
    print(f"服务地址: http://{host}:{port}")
    print(f"API 文档: http://{host}:{port}/docs")
    print(f"预设简历: {DEFAULT_RESUME_PATH}")
    print(f"日志文件: {LOG_FILE_PATH}")
    print(f"=" * 50)
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
