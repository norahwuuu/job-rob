# LinkedIn 智能求职助手 - 开发规范文档

## 📁 项目结构

```
LinkedIn-Collect/                    # 主项目目录
├── run_pipeline.py                  # 🚀 统一入口脚本
├── pipeline_config.yaml             # 📋 统一配置文件
├── linkedin_scraper.py              # 爬虫核心
├── scraper_config.yaml              # 爬虫配置 (自动同步)
├── jobs_progress.json               # 爬取结果
├── output/                          # 输出目录
│   ├── application_tracker.json     # 进度追踪
│   └── 2026-02-28/                  # 按日期组织
│       ├── easy_apply/              # Easy Apply 岗位
│       └── manual_apply/            # 手动申请岗位
├── logs/                            # 日志目录
└── agent.md                         # 本文档

resume_AI_editor/Word Editor/         # 简历编辑项目
├── resume_modifier/
│   ├── ai_analyzer.py               # AI分析器
│   ├── pdf_exporter.py              # PDF导出
│   └── ...
├── .env                             # 环境变量 (自动同步)
└── config.py

Auto_job_applier_linkedIn/           # 自动申请项目
├── runAiBot.py                      # 主程序
├── config/
│   ├── secrets.py                   # 凭据 (自动同步)
│   ├── settings.py
│   ├── search.py
│   └── questions.py
└── ...
```

## 🔧 配置同步机制

统一配置文件 `pipeline_config.yaml` 会自动同步到：

| 配置项 | LinkedIn-Collect | Word Editor | Auto_job_applier |
|--------|-----------------|-------------|------------------|
| LinkedIn凭据 | scraper_config.yaml | - | config/secrets.py |
| Gemini API Key | scraper_config.yaml | .env | config/secrets.py |
| Gemini Model | scraper_config.yaml | .env | - |

### 同步触发时机
- 运行 `run_pipeline.py` 时自动同步
- 调用 `ConfigManager.sync_to_projects()` 时

## 💰 Token 计费追踪

### 价格表 (2026年)

| 模型 | 输入价格 | 输出价格 |
|------|----------|----------|
| Gemini 3 Flash | $0.075/1M tokens | $0.30/1M tokens |
| GPT-4 | $30/1M tokens | $60/1M tokens |

### 使用方式

```python
from run_pipeline import token_tracker

# 每次API调用后记录
token_tracker.add_usage(
    input_tokens=1000,
    output_tokens=500,
    model="gemini-3-flash-preview"
)

# 打印汇总
token_tracker.print_summary()
```

### 输出示例
```
==================================================
💰 API Token 使用统计
==================================================
API调用次数: 15
输入 tokens: 45,000
输出 tokens: 12,000
总计 tokens: 57,000
预估费用: $0.0074 USD (约 ¥0.05)
==================================================
```

## 📂 输出文件结构

所有文件同一层级，便于操作：

```
output/2026-02-28/manual_apply/
├── 001_Google_AIEngineer_92分.url      ← 双击打开申请页
├── 001_Google_AIEngineer_92分.pdf      ← 上传这个简历
├── 001_Google_AIEngineer_92分_info.txt ← 岗位详情+JD
├── 002_Meta_MLEngineer_88分.url
├── 002_Meta_MLEngineer_88分.pdf
├── 002_Meta_MLEngineer_88分_info.txt
├── _待申请列表.txt                      ← 汇总清单
└── ...
```

### 命名规则
- 格式: `{编号}_{公司}_{职位}_{分数}分.{扩展名}`
- URL 和 PDF 同名，排序时相邻
- `_info.txt` 合并了 job_info 和 JD

## 🔄 状态流转

```
pending → resume_generated → applied
                          ↘ skipped
                          ↘ failed
```

### 状态说明
- `pending`: 待处理
- `resume_generated`: 简历已生成
- `applied`: 已申请
- `skipped`: 跳过
- `failed`: 失败

## 🎮 命令参考

```bash
# 完整流程
python run_pipeline.py

# 分步执行
python run_pipeline.py crawl      # 爬取岗位
python run_pipeline.py generate   # 生成简历
python run_pipeline.py apply      # 自动申请

# 管理
python run_pipeline.py status     # 查看进度
python run_pipeline.py open       # 打开输出文件夹
python run_pipeline.py done 001   # 标记完成
python run_pipeline.py done all   # 全部标记完成
python run_pipeline.py skip 002   # 跳过
```

## 🐛 调试技巧

### 查看详细日志
日志文件在 `logs/pipeline_*.log`

### 手动测试 Word Editor
```python
sys.path.insert(0, "path/to/Word Editor/resume_modifier")
from ai_analyzer import AIAnalyzer
analyzer = AIAnalyzer(provider="gemini", api_key="xxx", model="gemini-3-flash-preview")
result = analyzer.analyze_and_modify("resume.docx", "JD text...")
```

### 检查配置同步
```python
from run_pipeline import ConfigManager
cm = ConfigManager()
cm.sync_to_projects()
```

## ⚠️ 注意事项

1. **首次登录**需要手动处理验证码
2. **API Key** 不要提交到 Git
3. **LinkedIn 反爬**：添加随机延迟，不要频繁请求
4. **简历格式**：基础简历必须是 .docx 格式才能AI定制

## 📝 待办事项

- [ ] 深度集成 Auto_job_applier（支持自定义简历路径）
- [ ] Web UI 管理界面
- [ ] 申请结果回调更新状态
- [ ] 支持更多 AI 提供商

## 🚨 开发守则 (Agent Instructions)

### 1. 代码集中化原则
- **禁止生成零散脚本**：不要创建 `test_xxx.py`, `temp_xxx.py`, `debug_xxx.py` 等一次性脚本。
- **功能整合**：所有新功能必须整合进现有的 `run_pipeline.py` (作为 Pipeline 类的方法) 或 `linkedin_scraper.py` (作为工具类/函数)。
- **保持目录整洁**：若必须创建新模块，请放入 `utils/` 或 `modules/` 子目录，并在 `agent.md` 中记录用途。
- **优先修改现有文件**：遇到问题优先修改/扩展现有代码，而不是通过新建文件绕过问题。
