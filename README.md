# Job Bot Monorepo

这个仓库由三个子项目组成，按流水线协作完成：

1. 职位爬取与筛选
2. 简历定制生成
3. Easy Apply 自动投递

## 子项目职责

- `LinkedIn-Collect-main`  
  负责流程编排与主状态管理（crawl / generate / apply / status），主状态文件是 `out/jobs_progress.json`。

- `resume_AI_editor-main/Word Editor`  
  负责把岗位 JD + 基础简历转为定制简历（docx/pdf）。

- `auto-apply-project`  
  负责根据 `easy_todo.txt` 或 `jobs_progress.json` 执行 Easy Apply 自动投递。

## 全流程（推荐）

在仓库根目录执行：

```bash
# 1) 查看状态
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py status

# 2) 爬取岗位
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py crawl

# 3) 生成简历（小批量）
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py generate --limit 5

# 4) 自动投递（小批量）
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --max 5
```

## 常用投递方式

```bash
# 按日期 easy_todo 投递
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --date 2026-04-16 --max 5

# 仅投递一个 job_id（幂等，已 applied 自动跳过）
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --job-id 4371167896 --max 1

# 直接指定 easy_todo 路径
./.venv/bin/python LinkedIn-Collect-main/run_pipeline.py apply --easy-todo /abs/path/easy_todo.txt --max 3
```

## 产物目录约定

- 统一输出目录：`out/`（仓库根目录）
- 主状态文件：`out/jobs_progress.json`
- 当日产物：`out/<date>/`
  - `easy_todo.txt`
  - `manual_todo.txt`
  - `job_list.txt`
  - `resumes/`
  - `easy_apply/`
  - `manual_apply/`

## 回归脚本

```bash
bash LinkedIn-Collect-main/scripts/smoke_regression.sh
```
