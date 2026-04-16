# 简历自动修改程序 (Resume Auto-Modifier)

基于 AI 分析岗位描述，智能修改 Word 简历并导出 PDF，提高 HR 筛选通过率。

## 功能特性

- **AI 智能分析**: 使用 GPT-4 分析岗位要求，自动生成修改建议
- **精确替换**: 在 Word 文档中精确定位并替换内容，保持原有格式
- **PDF 导出**: 自动将修改后的简历转换为 PDF
- **API 服务**: 提供 RESTful API，便于浏览器插件集成

## 快速开始

### 1. 安装依赖

```bash
cd "Word Editor"
pip install -r requirements.txt
```

### 2. 配置 API 密钥

创建 `.env` 文件：

```env
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o
```

或设置环境变量：

```bash
# Windows PowerShell
$env:OPENAI_API_KEY = "sk-your-api-key-here"

# Linux/Mac
export OPENAI_API_KEY="sk-your-api-key-here"
```

### 3. 运行程序

#### 命令行方式

```bash
python -m resume_modifier.main \
    --resume "cv.docx" \
    --job "需要一个工作经历在中国的AI开发工程师，要求5年以上经验" \
    --output "./output"
```

#### API 服务方式

启动服务：

```bash
python -m resume_modifier.api_server
```

调用 API：

```bash
curl -X POST "http://127.0.0.1:8000/api/modify-resume" \
    -F "resume=@cv.docx" \
    -F "job_description=需要工作经历在中国的AI开发工程师"
```

## 命令行参数

```
选项:
  -r, --resume PATH      简历 Word 文档路径 [必需]
  -j, --job TEXT         岗位描述（文本或文件路径）[必需]
  -o, --output PATH      输出目录（默认: ./output）
  -n, --name TEXT        输出文件名（不含扩展名）
  -k, --api-key TEXT     OpenAI API 密钥
  --skip-pdf             跳过 PDF 生成
  --json-output          以 JSON 格式输出结果
  -v, --verbose          详细输出
  --help                 显示帮助信息
```

## API 接口

### 修改简历

```
POST /api/modify-resume
Content-Type: multipart/form-data

参数:
- resume: 简历文件 (.docx)
- job_description: 岗位描述
- skip_pdf: 是否跳过 PDF (可选)
- api_key: OpenAI API 密钥 (可选)

响应:
{
    "success": true,
    "task_id": "abc12345",
    "word_url": "/api/download/abc12345/resume.docx",
    "pdf_url": "/api/download/abc12345/resume.pdf",
    "match_score": 85,
    "modifications": [...],
    "suggestions": [...]
}
```

### 下载文件

```
GET /api/download/{task_id}/{filename}
```

### API 文档

启动服务后访问: http://127.0.0.1:8000/docs

## 项目结构

```
Word Editor/
├── resume_modifier/
│   ├── __init__.py          # 包初始化
│   ├── __main__.py          # 模块入口
│   ├── main.py              # 主程序 & CLI
│   ├── resume_parser.py     # 简历解析器
│   ├── ai_analyzer.py       # AI 分析引擎
│   ├── content_modifier.py  # 内容修改器
│   ├── pdf_exporter.py      # PDF 导出器
│   └── api_server.py        # FastAPI 服务
├── config.py                # 配置文件
├── requirements.txt         # 依赖列表
├── README.md               # 说明文档
└── cv.docx  # 示例简历
```

## 工作原理

```
输入                    处理                     输出
┌─────────────┐    ┌─────────────────┐    ┌──────────────┐
│ 岗位描述    │───▶│ AI 分析引擎     │───▶│ 修改指令JSON │
└─────────────┘    │ (GPT-4)         │    └──────┬───────┘
                   └─────────────────┘           │
┌─────────────┐    ┌─────────────────┐           │
│ Word 简历   │───▶│ 简历解析器      │           │
└─────────────┘    │ (python-docx)   │           │
                   └────────┬────────┘           │
                            │                    │
                            ▼                    ▼
                   ┌─────────────────────────────────┐
                   │        内容修改器               │
                   │  (精确替换，保持格式)           │
                   └────────────────┬────────────────┘
                                    │
                            ┌───────┴───────┐
                            ▼               ▼
                   ┌──────────────┐  ┌──────────────┐
                   │ 修改后 Word  │  │    PDF       │
                   └──────────────┘  └──────────────┘
```

## 如何快速读懂代码（建议阅读顺序）

如果你想从“能跑起来”到“看懂实现”，建议按这个顺序：

1. `resume_modifier/api_server.py`
   - 看 API 入口、任务状态管理、异步线程池处理。
   - 先理解外部（浏览器插件/前端）是如何调用后端的。
2. `resume_modifier/main.py`
   - 看 `process_resume()` 这个核心编排函数。
   - 它按顺序执行：解析简历 -> AI 生成指令 -> 应用修改 -> 导出 PDF。
3. `resume_modifier/resume_parser.py`
   - 看如何把 Word 简历转成结构化文本，供 AI 分析。
4. `resume_modifier/ai_analyzer.py`
   - 看 Prompt、模型调用、JSON 解析容错、指令后处理（如加粗修正）。
5. `resume_modifier/content_modifier.py`
   - 看 Word run/paragraph 级替换逻辑，这里是“格式不乱”的关键。
6. `resume_modifier/pdf_exporter.py`
   - 看 docx -> pdf 的平台适配逻辑（Windows/LibreOffice）。

### 代码与功能一一对应

- **“为什么要改这些内容”**：`ai_analyzer.py` 里由模型输出 `modifications`
- **“怎么精确改到 Word 里”**：`content_modifier.py` 里做匹配与替换
- **“一次请求怎么走完整链路”**：`api_server.py` -> `main.py:process_resume()`
- **“历史记录和统计在哪里”**：`job_log.py` + `api_server.py` 的 `/api/logs*` 端点
- **“最终文件怎么命名”**：`api_server.py` 中按公司名/岗位名生成安全文件名

### 首次调试建议

1. 启动后端后先访问 `http://127.0.0.1:8000/health`。
2. 再访问 `http://127.0.0.1:8000/docs` 用 Swagger 手动调 `POST /api/modify-resume`。
3. 若修改失败，先看终端日志里的 target/replacement，再对照 `content_modifier.py` 的匹配规则。
4. 优先确认：
   - 简历文件是否被 Word 占用
   - target 是否真实存在于简历文本
   - `match_type` 是否选对（大多数场景使用 `fuzzy`）

## 注意事项

1. **PDF 转换**: Windows 上需要安装 Microsoft Word；其他平台需要 LibreOffice
2. **API 密钥**: 请妥善保管 OpenAI API 密钥，不要提交到代码仓库
3. **简历真实性**: AI 只会调整表述方式，不会捏造不存在的经历

## 浏览器插件集成

API 服务支持 CORS，可以直接从浏览器插件调用：

```javascript
// 浏览器插件示例代码
const formData = new FormData();
formData.append('resume', resumeFile);
formData.append('job_description', jobDescription);

const response = await fetch('http://127.0.0.1:8000/api/modify-resume', {
    method: 'POST',
    body: formData
});

const result = await response.json();
if (result.success) {
    // 下载修改后的文件
    window.open(`http://127.0.0.1:8000${result.pdf_url}`);
}
```

## License

MIT
