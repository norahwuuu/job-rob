# resume-customizer handbook

这份文档是 `resume-customizer` 的统一说明，合并了历史的快速开始、使用指南和结构导读。

## 模块结构

- `word_editor/`：Python 后端，负责 JD 分析、简历改写、导出和 API。
- `web-to-pdf-plugin/web-to-md-pdf-plugin/`：浏览器插件，负责提取网页职位描述并请求后端。

## 快速开始

```bash
cd "resume-customizer/word_editor"
python -m pip install -r requirements.txt
python -m resume_modifier.api_server
```

服务启动后可访问 `http://127.0.0.1:8000/docs`。

## 端到端流程

1. 浏览器插件提取网页职位描述。
2. 插件调用 `POST /api/modify-resume`。
3. 后端执行：解析简历 -> AI 生成修改指令 -> 修改 docx -> 可选导出 pdf。
4. 插件轮询任务状态并展示结果，用户下载文件。

## 关键文件

- `word_editor/resume_modifier/api_server.py`：FastAPI 入口与任务调度。
- `word_editor/resume_modifier/main.py`：核心编排流程。
- `word_editor/resume_modifier/ai_analyzer.py`：模型调用与 JSON 容错解析。
- `word_editor/resume_modifier/content_modifier.py`：Word 文档文本匹配与写入。
- `word_editor/resume_modifier/pdf_exporter.py`：PDF 导出。
- `word_editor/resume_modifier/job_log.py`：申请日志与统计。

## 常见 API

- `POST /api/modify-resume`
- `GET /api/task-status/{task_id}`
- `GET /api/download/{task_id}/{filename}`
- `GET /api/logs`
- `GET /api/logs/stats`
- `GET /api/health`

## 故障排查

- **后端未启动**：检查 `http://127.0.0.1:8000/api/health`。
- **未找到目标文本**：检查 `content_modifier.py` 的匹配逻辑和 AI 返回的 `target`。
- **JSON 解析失败**：检查 `ai_analyzer.py` 的容错与修复日志。
- **文件写入失败**：确认目标 docx 未被 Word 占用。

## 相关文档

- 子项目总览：`word_editor/README.md`
- 插件与集成细节：`INTEGRATION_GUIDE.md`
