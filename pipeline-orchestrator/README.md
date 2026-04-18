# pipeline-orchestrator

此子项目职责：**流程编排与主状态管理**。  
它负责串起爬取、生成、投递三个阶段，并维护主状态文件 `artifacts/jobs_progress.json`。

## 负责范围

- `crawl / crawl-detail`：职位抓取与进度落盘
- `generate`：调用 word_editor 生成定制简历并回写 `resume_path`
- `apply`：先调用 `auto-apply-project` 生成 `easy_apply_answers/*.json`，再（默认）用 Selenium 打开 `easy_todo` 中岗位并点击 Easy Apply 填表（见 `easy_apply_browser.py`、`advanced.easy_apply_browser`；`--no-browser` 可仅生成 JSON）
- `status`：输出统一进度统计与费用统计

## 主入口

```bash
# 在仓库根目录执行
./.venv/bin/python pipeline-orchestrator/run_pipeline.py <command>
```

常用命令：

```bash
./.venv/bin/python pipeline-orchestrator/run_pipeline.py crawl
./.venv/bin/python pipeline-orchestrator/run_pipeline.py generate --limit 5
./.venv/bin/python pipeline-orchestrator/run_pipeline.py apply --max 5
./.venv/bin/python pipeline-orchestrator/run_pipeline.py apply --max 5 --no-browser
./.venv/bin/python pipeline-orchestrator/run_pipeline.py status
```

定向投递：

```bash
./.venv/bin/python pipeline-orchestrator/run_pipeline.py apply --date 2026-04-16 --max 5
./.venv/bin/python pipeline-orchestrator/run_pipeline.py apply --job-id 4371167896 --max 1
./.venv/bin/python pipeline-orchestrator/run_pipeline.py apply --easy-todo /abs/path/easy_todo.txt --max 3
```

## 本项目核心文件

- `run_pipeline.py`：总入口与流程编排
- `pipeline_config.yaml`：流程配置（可被环境变量覆盖）
- `scraper_config.yaml`：爬取配置
- `scripts/smoke_regression.sh`：最小回归脚本
- `scripts/normalize_artifact_filenames.py`：历史产物命名迁移工具
- `scripts/optimize_artifacts_layout.py`：`artifacts/` 目录布局整理工具

## 状态与产物约定（由本项目维护）

- 主状态文件：`artifacts/jobs_progress.json`
- 阶段结果：`artifacts/apply_results.json`、`artifacts/logs/*.log`
- 当日产物：`artifacts/<date>/easy_todo.txt`、`manual_todo.txt`、`summary.json`

> 全流程说明请看仓库根目录 `README.md`。

## artifacts 目录命名整理

```bash
# 预览改动
python pipeline-orchestrator/scripts/optimize_artifacts_layout.py

# 执行改动
python pipeline-orchestrator/scripts/optimize_artifacts_layout.py --apply
```
