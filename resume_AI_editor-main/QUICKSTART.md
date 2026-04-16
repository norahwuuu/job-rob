# 简历优化助手 - 快速开始

## ✅ 完成的集成工作

### 后端 (Python)
- ✅ **job_log.py**: 完整的日志系统，记录公司名、岗位名、网页URL、修改详情
- ✅ **ai_analyzer.py**: AI 自动提取公司名和岗位名
- ✅ **content_modifier.py**: 返回每条修改的成功/失败状态
- ✅ **api_server.py**: 
  - 使用预设简历路径 (不需要每次上传)
  - 接收 `source_url` 参数
  - PDF 文件名: `Candidate_Resume_{公司名}_{岗位名}.pdf`
  - 新增 `/api/logs` 和 `/api/logs/stats` 端点
  - 每次调用自动保存日志
- ✅ **config.py**: 添加 `DEFAULT_RESUME_PATH` 和 `LOG_FILE_PATH`
- ✅ **tray_launcher.py**: Windows 系统托盘启动器
- ✅ **startup.bat**: 开机自启脚本

### 前端 (浏览器插件)
- ✅ **manifest.json**: 添加必要权限 (`downloads`, `storage`, `host_permissions`)
- ✅ **popup.html**: 全新 UI 设计
  - 优化按钮
  - 修改详情面板（显示成功/失败状态）
  - 双下载按钮（PDF + Word）
  - 历史记录按钮
- ✅ **popup.js**: 完整实现
  - 提取网页内容
  - 调用后端 API
  - 显示详细修改结果
  - 下载文件
  - 查看历史记录

## 🎯 核心特性

### 1. 智能文件命名
```
Candidate_Resume_Microsoft_Senior_AI_Engineer.pdf
Candidate_Resume_Google_ML_Researcher.pdf
Candidate_Resume_Amazon_Software_Developer.pdf
```

### 2. 详细修改追踪
```
✅ "Beijing, China" → "Seattle, WA" (匹配岗位地点)
✅ "3 years" → "5+ years AI experience" (突出相关经验)
❌ "某某技能" (未找到原文，请手动添加)
```

### 3. 完整日志记录
- 时间戳
- 公司名 + 岗位名
- 来源网页 URL
- 所有修改详情（成功/失败）
- 匹配度评分
- 生成的文件路径

### 4. 双格式下载
- **PDF**: 直接投递用
- **Word**: 手动调整用（如果有修改不满意）

## 🚀 立即使用

### 0) 先确认当前仓库下的实际路径（推荐）

本文很多命令示例使用的是历史 Windows 绝对路径。  
如果你是在当前仓库直接运行，建议优先使用相对路径：

```bash
cd "Word Editor"
python -m pip install -r requirements.txt
python -m resume_modifier.api_server
```

这样更通用，也更不容易因为本地目录不同而报错。

### 步骤 1: 安装依赖
```powershell
cd "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor"
python -m pip install -r requirements.txt
```

### 步骤 2: 准备简历
确保文件存在:
```
C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor\cv.docx
```

### 步骤 3: 配置 OpenAI API Key
在 `Word Editor` 目录创建 `.env` 文件:
```env
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4
```

### 步骤 4: 启动后端
```powershell
# 方式 1: 命令行启动
python -m resume_modifier.api_server

# 方式 2: 托盘启动（推荐）
python tray_launcher.py
```

### 步骤 5: 安装浏览器插件
1. 打开 Chrome: `chrome://extensions/`
2. 开启「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择: `web-to-pdf-plugin/web-to-md-pdf-plugin`

### 步骤 6: 测试
1. 访问任意招聘网站
2. 找到目标职位
3. 点击浏览器插件图标
4. 点击「✨ 提取职位描述并优化简历」
5. 查看修改详情
6. 下载 PDF 或 Word

## 📊 API 端点

### 核心端点
- `POST /api/modify-resume` - 优化简历
- `GET /api/download/{task_id}/{filename}` - 下载文件
- `GET /api/logs` - 获取申请日志
- `GET /api/logs/stats` - 获取统计信息
- `GET /api/health` - 健康检查

### 使用示例
```powershell
# 健康检查
Invoke-WebRequest http://127.0.0.1:8000/api/health

# 查看所有日志
Invoke-WebRequest http://127.0.0.1:8000/api/logs | ConvertFrom-Json

# 按公司查询
Invoke-WebRequest "http://127.0.0.1:8000/api/logs?company=Microsoft" | ConvertFrom-Json

# 统计信息
Invoke-WebRequest http://127.0.0.1:8000/api/logs/stats | ConvertFrom-Json
```

## 📁 文件结构

```
resume_AI_editor/
├── Word Editor/
│   ├── cv.docx    ← 你的简历文件
│   ├── config.py                       ← 配置文件
│   ├── tray_launcher.py                ← 托盘启动器
│   ├── startup.bat                     ← 开机自启脚本
│   ├── test_setup.py                   ← 测试脚本
│   ├── resume_modifier/
│   │   ├── api_server.py              ← API 服务器 ⭐
│   │   ├── job_log.py                 ← 日志系统 ⭐
│   │   ├── ai_analyzer.py             ← AI 分析 ⭐
│   │   ├── content_modifier.py        ← 内容修改 ⭐
│   │   └── ...
│   └── output/
│       ├── application_logs.json      ← 申请日志
│       └── results/                   ← 生成的简历
│
└── web-to-pdf-plugin/
    └── web-to-md-pdf-plugin/
        ├── manifest.json              ← 插件配置 ⭐
        ├── popup.html                 ← 插件 UI ⭐
        ├── popup.js                   ← 插件逻辑 ⭐
        └── content.js                 ← 内容提取
```

## 🔍 如何查找历史简历

### 按公司名查找
```powershell
# 查找所有 Microsoft 的申请
$logs = Invoke-WebRequest "http://127.0.0.1:8000/api/logs?company=Microsoft" | ConvertFrom-Json
$logs.logs | Format-Table company_name, job_title, timestamp
```

### 查看文件路径
```powershell
# 查看最近 10 条申请的文件路径
$logs = Invoke-WebRequest "http://127.0.0.1:8000/api/logs?limit=10" | ConvertFrom-Json
$logs.logs | Select-Object company_name, job_title, pdf_path
```

### 打开输出目录
```powershell
# 打开所有生成的简历文件夹
explorer "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor\output\results"
```

## 🎓 高级技巧

### 1. 查看详细修改记录
点击插件中的「📋 查看申请历史」，可以看到:
- 申请时间
- 公司和岗位
- 匹配度
- 成功/失败统计

### 2. 手动调整不满意的修改
如果某些修改不满意:
1. 点击「📝 下载 Word」
2. 在 Word 中手动调整
3. 导出为 PDF

### 3. 批量查看历史
```powershell
# 查看所有申请的统计
Invoke-WebRequest http://127.0.0.1:8000/api/logs/stats | ConvertFrom-Json

# 输出示例:
# total_applications: 15
# companies: ["Microsoft", "Google", "Amazon"]
# average_match_score: 85.2
# success_rate: 88.5
```

## ⚠️ 重要提示

1. **后端必须先启动**: 插件需要后端 API 服务器运行
2. **简历文件不能打开**: 处理时 Word 中不能打开简历文件
3. **OpenAI API Key**: 必须配置才能使用 AI 分析
4. **网络连接**: 需要能访问 OpenAI API

## 🐛 问题排查

### 插件显示「后端服务未启动」
```powershell
# 启动后端
python -m resume_modifier.api_server
```

### 所有修改都失败
- 检查简历文件是否存在
- 确保是 .docx 格式
- 查看控制台日志

### PDF 文件名乱码
- 文件名会自动过滤特殊字符
- 空格会被保留
- 过长会被截断（50 字符）

---

**准备好了吗？** 运行 `python test_setup.py` 检查配置！
