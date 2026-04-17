# Word Editor

此子项目职责：**简历定制引擎**。  
输入岗位 JD 和基础简历，输出修改后的 Word/PDF 简历。

## 负责范围

- `resume_modifier/ai_analyzer.py`：生成修改指令（含 JSON 容错修复）
- `resume_modifier/content_modifier.py`：把修改指令应用到 Word 文档
- `resume_modifier/pdf_exporter.py`：导出 PDF
- `resume_modifier/api_server.py`：提供 API 服务（供上层流程调用）

## 本地运行

```bash
cd "resume_AI_editor-main/Word Editor"
pip install -r requirements.txt
python -m resume_modifier.main --resume "cv.docx" --job "job description" --output "./output"
```

## API 模式（可选）

```bash
python -m resume_modifier.api_server
```

## 关键配置

- `.env` 中配置：
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
  - `OPENAI_BASE_URL`

## 调试产物

- JSON 解析失败会落盘到：`out/logs/broken_ai_json_*.txt`

> 全流程说明请看仓库根目录 `README.md`。
