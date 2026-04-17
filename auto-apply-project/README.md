# auto-apply-project

此子项目职责：**Easy Apply 执行器**。  
读取 `easy_todo.txt` 或 `jobs_progress.json`，执行 Easy Apply 投递并输出结果。

## 负责范围

- 解析输入源（`run-easy` / `run-easy-todo`）
- 投递状态机执行（`OPENED -> REVIEW -> SUBMITTED`）
- 输出结果文件：
  - `apply_results.json`
  - `auto_applied.json`
  - `manual_todo.json`

## 运行方式

```bash
cd auto-apply-project
python -m auto_apply.main report

# 从 jobs_progress 读取
python -m auto_apply.main --data-dir ../artifacts run-easy \
  --jobs-progress ../artifacts/jobs_progress.json \
  --max 10

# 从 easy_todo 读取（推荐）
python -m auto_apply.main --data-dir ../artifacts run-easy-todo \
  --easy-todo ../artifacts/2026-04-16/easy_todo.txt \
  --jobs-progress ../artifacts/jobs_progress.json \
  --max 5
```

## 额外能力

- 幂等过滤：`--jobs-progress` 中已 `applied` 的岗位会自动跳过
- 单条投递：`--job-id <id>`
- 国家联系方式：支持 Germany / Switzerland 自动填充
- **简历驱动的填表建议**：从 `resume_path` 指向的 PDF（或 `.txt`/`.md`）抽取正文，扫描邮箱/电话，并与 `PERSONAL_*` 环境变量、`easy_todo` 中的联系方式合并；默认再调用 **OpenAI 兼容 API**（`OPENAI_API_KEY`，可选 `OPENAI_BASE_URL`）补全常见筛查字段（工签、离职周期、年限等）。结果写入 `--data-dir` 下的 `easy_apply_answers/<job_id>.json`，并出现在 `apply_results.json` / `auto_applied.json` 对应条目的 `easy_apply_answers` 字段。
  - 关闭 LLM，仅规则合并：`--no-ai` 或环境变量 `APPLY_USE_AI_FILL=false`
  - 模型：`APPLY_AI_MODEL` 或 `OPENAI_MODEL`（默认 `gpt-4o-mini`）

> 说明：当前子项目仍**不驱动浏览器**在 LinkedIn 页面上自动点击；生成的是可直接对照填写的结构化答案。全流程说明请看仓库根目录 `README.md`。
