# pipeline-orchestrator agent notes

此文档用于维护当前项目的开发约束，确保新增改动与现有流水线一致。

## 当前架构（2026）

- 编排层：`pipeline-orchestrator/run_pipeline.py`
- 简历层：`resume-customizer/word_editor`
- 投递层：`auto-apply-project`
- 统一产物目录：`artifacts/`

## 关键原则

1. 优先修改现有入口，不新增临时脚本绕过流程。
2. 产物和状态统一落到 `artifacts/`，避免多套输出目录。
3. 兼容改动优先：涉及路径或命名变更时，先加兼容再迁移。
4. 不在仓库中保留隐私数据、历史备份和临时调试文件。

## 代码组织约定

- 流程控制和状态同步：放在 `run_pipeline.py`
- 抓取与筛选能力：放在 `linkedin_scraper.py`
- 运维脚本：放在 `scripts/`
- 文档说明：保持“根 README 讲全流程，子项目 README 讲本职责”

## 提交前检查

- `./.venv/bin/python pipeline-orchestrator/run_pipeline.py status`
- 关键路径引用是否仍指向：
  - `pipeline-orchestrator/`
  - `resume-customizer/word_editor/`
  - `auto-apply-project/`
  - `artifacts/`
- 无新增敏感文件、无多余历史数据
