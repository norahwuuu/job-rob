# 简历优化助手 - 集成使用指南

浏览器插件 + Python 后端，从招聘网页一键生成定制简历。

## 🎯 功能特性

### ✨ 核心功能
- **一键优化**: 从招聘网页提取职位描述，自动优化简历
- **智能命名**: PDF 文件名格式 `Candidate_Resume_{公司名}_{岗位名}.pdf`
- **详细日志**: 记录每次申请的公司、岗位、修改详情、网页地址
- **修改追踪**: 清晰显示每条修改是否成功及失败原因
- **双格式下载**: 提供 Word（可手动编辑）和 PDF（直接投递）两种格式
- **历史查询**: 按公司名查询历史申请记录

### 📊 显示内容
- 公司名称和岗位名称（AI 自动提取）
- 匹配度评分
- 每条修改的详细状态（✅成功 / ❌失败）
- AI 建议（无法自动修改的内容）
- 修改统计（成功 5/6 等）

## 📦 安装步骤

### 1. Python 后端设置

```powershell
cd "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor"

# 安装依赖
pip install -r requirements.txt

# 配置简历路径（在 config.py 中已预设）
# DEFAULT_RESUME_PATH = "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor\cv.docx"

# 确保简历文件存在
# 将你的简历重命名为 cv.docx 并放在 Word Editor 目录
```

### 2. 浏览器插件安装

1. 打开 Chrome 浏览器
2. 访问 `chrome://extensions/`
3. 开启右上角「开发者模式」
4. 点击「加载已解压的扩展程序」
5. 选择文件夹: `C:\Users\<your-user>\Work_Project\resume_AI_editor\web-to-pdf-plugin\web-to-md-pdf-plugin`

## 🚀 使用方法

### 方式 1: 手动启动（推荐先测试）

```powershell
cd "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor"

# 启动 API 服务器
python -m resume_modifier.api_server
```

服务器启动后，访问 http://127.0.0.1:8000/docs 查看 API 文档。

### 方式 2: 系统托盘启动（推荐日常使用）

```powershell
cd "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor"

# 启动托盘图标
python tray_launcher.py

# 或直接双击 startup.bat
```

托盘图标功能：
- 🟢 启动/停止服务器
- 📂 打开日志目录
- 📁 打开输出目录
- 🌐 打开 API 文档
- ❌ 退出

### 方式 3: 开机自启动

1. 按 `Win + R`
2. 输入 `shell:startup` 并回车
3. 将 `startup.bat` 的快捷方式拖到打开的文件夹中

## 📖 使用流程

### 完整流程示例

1. **启动后端服务**
   ```powershell
   python -m resume_modifier.api_server
   # 或运行 startup.bat（推荐）
   ```

2. **浏览招聘网站**
   - 打开任意招聘网站（LinkedIn、Boss直聘、51Job 等）
   - 找到目标职位

3. **点击插件优化**
   - 点击浏览器工具栏中的「简历优化助手」图标
   - 点击「✨ 提取职位描述并优化简历」按钮
   - 等待 AI 分析（通常 10-30 秒）

4. **查看修改详情**
   ```
   ✅ "Beijing, China" → "Remote" (匹配远程岗位要求)
   ✅ "3 years experience" → "3+ years AI development experience"
   ❌ "某某技能" (未找到原文)
   ```

5. **下载简历**
   - 点击「📄 下载 PDF」直接投递
   - 点击「📝 下载 Word」手动调整

6. **查看历史记录**
   - 点击「📋 查看申请历史」查看所有申请记录
   - 文件名示例: `Candidate_Resume_Microsoft_Senior_AI_Engineer.pdf`

## 📝 日志系统

### 日志位置
```
Word Editor/output/application_logs.json
```

### 日志内容
```json
{
  "timestamp": "2026-02-02T10:30:00",
  "company_name": "Microsoft",
  "job_title": "Senior AI Engineer",
  "source_url": "https://careers.microsoft.com/job/12345",
  "match_score": 85,
  "success_count": 5,
  "total_count": 6,
  "modifications": [
    {
      "target": "Beijing, China",
      "replacement": "Redmond, WA",
      "reason": "匹配岗位地点",
      "success": true
    }
  ],
  "word_path": "output/results/abc123/Candidate_Resume_Microsoft_Senior_AI_Engineer.docx",
  "pdf_path": "output/results/abc123/Candidate_Resume_Microsoft_Senior_AI_Engineer.pdf"
}
```

### 查询日志

**通过 API 查询**:
```powershell
# 获取所有日志
Invoke-WebRequest http://127.0.0.1:8000/api/logs | ConvertFrom-Json

# 按公司名查询
Invoke-WebRequest "http://127.0.0.1:8000/api/logs?company=Microsoft" | ConvertFrom-Json

# 获取统计信息
Invoke-WebRequest http://127.0.0.1:8000/api/logs/stats | ConvertFrom-Json
```

**通过插件查询**:
- 点击「📋 查看申请历史」按钮

## 🔧 配置文件

### config.py 关键配置

```python
# 预设简历路径（必须配置）
DEFAULT_RESUME_PATH = r"C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor\cv.docx"

# 日志文件路径
LOG_FILE_PATH = "output/application_logs.json"

# API 服务配置
API_HOST = "127.0.0.1"
API_PORT = 8000

# OpenAI API 配置（需在 .env 文件中配置）
OPENAI_API_KEY = "your_api_key_here"
OPENAI_MODEL = "gpt-4"
```

### .env 文件示例

在 `Word Editor` 目录创建 `.env` 文件:

```env
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4
OUTPUT_DIR=./output
```

## ⚠️ 注意事项

### 1. 简历文件要求
- **必须是 .docx 格式**（不支持 .doc）
- 文件名必须为 `cv.docx`
- 放在 `Word Editor` 目录下
- **不要在 Word 中打开简历文件**（会导致文件被锁定）

### 2. 修改失败常见原因
- ❌ **未找到原文**: AI 返回的目标文本在简历中不存在
  - 解决: 下载 Word 文件手动修改
- ❌ **文本太短**: 目标文本少于 3 个字符，跳过以避免误匹配
- ❌ **文本太长**: 目标文本超过 200 个字符，匹配困难

### 3. 网页提取问题
- 某些网站的内容是动态加载的，可能提取不完整
- 建议在职位描述加载完成后再点击插件
- 如果提取失败，可以复制职位描述手动调用 API

### 4. 后端服务状态
- 插件启动时会自动检测后端是否运行
- 如显示「⚠️ 后端服务未启动」，需先启动 Python 服务器
- 服务器必须在 `http://127.0.0.1:8000` 运行

## 🐛 故障排查

### 问题 1: 插件显示「后端服务未启动」
```powershell
# 检查服务器是否运行
Invoke-WebRequest http://127.0.0.1:8000/api/health

# 如果失败，启动服务器
python -m resume_modifier.api_server
```

### 问题 2: 提示「预设简历文件不存在」
```powershell
# 检查文件是否存在
Test-Path "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor\cv.docx"

# 确保文件名完全匹配，包括扩展名
```

### 问题 3: PDF 生成失败
- 确保安装了 Microsoft Word（Windows）
- PDF 生成失败不影响 Word 文件，可手动转换

### 问题 4: AI 提取的公司名/岗位名不准确
- AI 会尽力从职位描述中提取，但可能不准确
- 文件名会自动过滤特殊字符，确保文件系统兼容
- 如需修改，可在日志中查看详细信息

### 问题 5: 所有修改都显示「未找到原文」
- 检查简历文件路径是否正确
- 确保简历是 .docx 格式
- 查看控制台日志查找详细错误信息

## 📊 API 端点说明

### POST /api/modify-resume
优化简历（插件调用）

**参数**:
- `job_description` (form): 职位描述文本
- `source_url` (form): 来源网页 URL
- `skip_pdf` (form): 是否跳过 PDF 生成

**响应**:
```json
{
  "success": true,
  "company_name": "Microsoft",
  "job_title": "Senior AI Engineer",
  "match_score": 85,
  "success_count": 5,
  "total_count": 6,
  "word_url": "/api/download/abc123/Candidate_Resume_Microsoft_Senior_AI_Engineer.docx",
  "pdf_url": "/api/download/abc123/Candidate_Resume_Microsoft_Senior_AI_Engineer.pdf",
  "modifications": [...]
}
```

### GET /api/logs
获取申请日志

**参数**:
- `limit` (query): 返回最近 N 条记录
- `company` (query): 按公司名筛选

### GET /api/logs/stats
获取统计信息

**响应**:
```json
{
  "total_applications": 10,
  "companies": ["Microsoft", "Google", "Amazon"],
  "average_match_score": 82.5,
  "success_rate": 85.0
}
```

## 🎓 高级用法

### 命令行直接调用

```powershell
cd "C:\Users\<your-user>\Work_Project\resume_AI_editor\Word Editor"

# 使用命令行工具
python -m resume_modifier.main `
  --resume "cv.docx" `
  --job "job_description.txt" `
  --output "output/custom"
```

### 自定义简历路径

修改 `config.py`:
```python
DEFAULT_RESUME_PATH = r"D:\My Documents\Resumes\MyResume.docx"
```

重启服务器使配置生效。

## 📈 未来改进建议

- [ ] 支持多个简历模板切换
- [ ] 插件中添加简历预览功能
- [ ] 更智能的职位信息提取（识别更多招聘网站结构）
- [ ] 支持批量处理多个职位
- [ ] 导出修改对比 HTML 报告

## 📞 技术支持

如遇到问题:
1. 查看控制台日志输出
2. 检查 `output/application_logs.json`
3. 访问 http://127.0.0.1:8000/docs 测试 API

---

**版本**: 2.0.0  
**最后更新**: 2026-02-02
