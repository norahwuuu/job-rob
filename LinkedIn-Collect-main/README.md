# LinkedIn-Collect (Pipeline)

基于 `run_pipeline.py` 的一体化流程：职位爬取 -> AI 筛选 -> 定制简历 -> 自动投递（可选）。

## 环境准备

推荐使用项目根目录 `job-bot/.venv`：

```bash
# 在 LinkedIn-Collect-main 目录
../.venv/bin/python -m pip install -r requirements.txt
```

## 配置说明

- 默认环境读取 `.env`
- 支持 `PIPELINE__A__B=...` 覆盖任意配置路径（映射到 `config.a.b`）

常见分组：
- `PERSONAL_*`：个人信息（邮箱、手机号、密码、命名前缀）
- `PIPELINE__SEARCH__*`：职位、地点、时间、页数、经验级别
- `PIPELINE__FILTER__*`：分数阈值、经验阈值、关键词过滤、公司偏好
- `PIPELINE__AI__*`：模型、预过滤、LLM 评分开关、API Key
- `PIPELINE__ADVANCED__*`：`batch_size`、`llm_delay`、`headless`
- `PIPELINE__OUTPUT__*`：输出目录（当前建议 `./out`）

### 推荐 `.env` 模板（可直接复制）

```env
# ------------------------------
# Personal
# ------------------------------
PERSONAL_EMAIL=your_email@example.com
PERSONAL_PHONE=+49xxxxxxxxxx
PERSONAL_LINKEDIN_PASSWORD=your_password
PERSONAL_FIRST_NAME=YourName
PERSONAL_RESUME_PREFIX=YourName_Resume

# ------------------------------
# Search
# ------------------------------
PIPELINE__SEARCH__POSITIONS=Frontend Developer
PIPELINE__SEARCH__LOCATIONS=Germany
PIPELINE__SEARCH__MAX_PAGES=3
PIPELINE__SEARCH__SORT_BY=DD
PIPELINE__SEARCH__TIME_FILTER=r86400
PIPELINE__SEARCH__AUTO_RESUME=false

# ------------------------------
# Filter
# ------------------------------
PIPELINE__FILTER__MIN_AI_SCORE=70
PIPELINE__FILTER__MIN_EXPERIENCE_YEARS=1
PIPELINE__FILTER__MAX_EXPERIENCE_YEARS=10
PIPELINE__FILTER__EXCLUDE_GERMAN=true

# ------------------------------
# AI
# ------------------------------
PIPELINE__AI__PROVIDER=gemini_relay
PIPELINE__AI__OPENAI_MODEL=gemini-2.5-flash
PIPELINE__AI__OPENAI_API_KEY=your_api_key
PIPELINE__AI__OPENAI_BASE_URL=https://api.vectorengine.ai/v1
PIPELINE__AI__ENABLE_PRE_FILTER=false
PIPELINE__AI__ENABLE_AI_PRE_FILTER=true
PIPELINE__AI__USE_LLM_SCORING=true

# ------------------------------
# Advanced
# ------------------------------
PIPELINE__ADVANCED__HEADLESS=false
PIPELINE__ADVANCED__BATCH_SIZE=1
PIPELINE__ADVANCED__LLM_DELAY=1.0

# ------------------------------
# Output
# ------------------------------
PIPELINE__OUTPUT__BASE_DIR=./out
PIPELINE__OUTPUT__BY_DATE=true
```

说明：
- `PIPELINE__AI__OPENAI_BASE_URL` 推荐填写 `https://api.vectorengine.ai/v1`。
- 即便误填 `https://api.vectorengine.ai` 或 `.../chat/completions`，程序也会自动规范化。

## 命令速查

### 方式 A：在 `LinkedIn-Collect-main` 目录执行

```bash
# 完整流程
../.venv/bin/python run_pipeline.py

# 仅爬取
../.venv/bin/python run_pipeline.py crawl

# 仅生成简历
../.venv/bin/python run_pipeline.py generate --limit 5
../.venv/bin/python run_pipeline.py generate --min-score 50

# 重新 LLM 评分（jobs_progress 里 ai_reason 为「LLM评分失败」或「未获取到评分」）
../.venv/bin/python run_pipeline.py rescore-llm
../.venv/bin/python run_pipeline.py rescore-llm --limit 30

# 仅自动申请 Easy Apply
../.venv/bin/python run_pipeline.py apply --max 10

# 查看状态
../.venv/bin/python run_pipeline.py status
```

### 方式 B：在 `job-bot` 根目录执行

```bash
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py crawl
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py generate
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py status
```

`run_pipeline.py status` 现会额外显示 `out/token_usage.json` 的历史累计 LLM token 与预估费用。

## 建议参数（稳定优先）

默认环境 `.env` 建议：
- `PIPELINE__SEARCH__MAX_PAGES=3`
- `PIPELINE__ADVANCED__BATCH_SIZE=1`
- `PIPELINE__ADVANCED__LLM_DELAY=1.0`

## 最近优化（2026-04）

- 日志去重：`run_pipeline.py` 已关闭 `pipeline` logger 向 root logger 传播，终端日志不再重复打印同一条消息。
- OpenAI 兼容地址规范化：自动将 `OPENAI_BASE_URL` / `AI_SERVER_URL` 规范为 API 根地址（必要时自动补 `/v1`，并自动去掉误填的 `/chat/completions`）。
- Word Editor 调用参数更稳：在同步配置与运行时调用时统一走规范化 URL，降低返回 HTML 页面导致 JSON 解析失败的概率。

推荐把以下任一形式都视为可接受输入（程序会自动规范化）：
- `https://api.vectorengine.ai`
- `https://api.vectorengine.ai/v1`
- `https://api.vectorengine.ai/chat/completions`（会被自动纠正）

## 快速自测（建议每次改配置后执行）

在 `LinkedIn-Collect-main` 目录：

```bash
# 1) 查看当前状态（是否能正常读到进度与 token 统计）
../.venv/bin/python run_pipeline.py status

# 2) 小批量生成回归（验证 Word Editor 链路）
../.venv/bin/python run_pipeline.py generate --limit 1
```

你应在日志中看到类似：
- `Word Editor AI请求参数 ... base_url=.../v1`
- 若外部网络波动，可能出现 `Connection error.`，此时会回退到基础简历并继续流程（属于预期容错行为）。

## 常见问题

- `ModuleNotFoundError: No module named 'yaml'`
  - 原因：用了系统 Python，不是 `.venv` 解释器
  - 解决：使用 `../.venv/bin/python`（子目录）或 `./.venv/bin/python`（根目录）

- `429 RESOURCE_EXHAUSTED`
  - 原因：中转 AI 通道配额或速率超限
  - 解决：降低 `batch_size`、提高 `llm_delay`、减小 `max_pages`，或更换可用中转 API Key

- 简历“看起来生成了但没改内容”
  - 常见于 LLM 调用失败回退到基础简历
  - 先检查日志中的 Word Editor / OpenAI 兼容接口错误信息
  - 重点确认日志里 `base_url` 是否为 `.../v1`（程序会自动规范化）

- `JSON 解析失败` 且响应前几百字符是 HTML
  - 常见原因：`OPENAI_BASE_URL` 配置成了网页地址或网关返回登录/落地页
  - 先确认 `.env` 的 API 地址可直连，再执行 `generate --limit 1` 做最小回归

- 新的一天没有从第一页开始爬取
  - 现已改为“跨天自动从第一页开始”：`auto_resume=true` 仅在同一天内续爬
  - 续爬键仍按 `position|location|sort_by` 区分；当天中断重跑会接着爬

## 注意事项

- `resume.json` 必须是标准 JSON（不允许注释）
- `Auto_job_applier_linkedIn` 不存在时，`apply` 不可用是预期行为
- `.env` 支持行尾注释，解析时会忽略注释部分
