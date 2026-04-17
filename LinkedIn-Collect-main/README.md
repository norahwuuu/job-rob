# LinkedIn-Collect-main

此子项目职责：**流程编排与主状态管理**。  
它负责串起爬取、生成、投递三个阶段，并维护主状态文件 `out/jobs_progress.json`。

## 负责范围

- `crawl / crawl-detail`：职位抓取与进度落盘
- `generate`：调用 Word Editor 生成定制简历并回写 `resume_path`
- `apply`：调用 `auto-apply-project` 执行 Easy Apply
- `status`：输出统一进度统计与费用统计

## 主入口

```bash
# 在仓库根目录执行
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py <command>
```

常用命令：

```bash
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py crawl
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py generate --limit 5
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --max 5
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py status
```

定向投递：

```bash
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --date 2026-04-16 --max 5
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --job-id 4371167896 --max 1
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --easy-todo /abs/path/easy_todo.txt --max 3
```

## 本项目核心文件

- `run_pipeline.py`：总入口与流程编排
- `pipeline_config.yaml`：流程配置（可被环境变量覆盖）
- `scraper_config.yaml`：爬取配置
- `scripts/smoke_regression.sh`：最小回归脚本
- `scripts/normalize_artifact_names.py`：历史产物命名迁移工具

## 状态与产物约定（由本项目维护）

- 主状态文件：`out/jobs_progress.json`
- 阶段结果：`out/apply_results.json`、`out/logs/*.log`
- 当日产物：`out/<date>/easy_todo.txt`、`manual_todo.txt`、`job_list.txt`

> 全流程说明请看仓库根目录 `README.md`。
