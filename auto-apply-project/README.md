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

> 全流程说明请看仓库根目录 `README.md`。
