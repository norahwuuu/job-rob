# Resume AI Editor - 使用指南

## 系统概览

本系统通过 AI 分析岗位描述（JD），自动生成简历修改指令，支持三种主要操作：

1. **fuzzy** - 替换现有文本（模糊匹配）
2. **add_after** - 在指定位置后添加新 bullet point
3. **replace_paragraph** - 重写整个段落/bullet

---

## ✅ 重要经验总结

### 1. Bullet 符号处理（关键！）

**规则：replacement 文本必须包含 bullet 符号（•）**

```json
// ✅ 正确示例
{
  "target": "Led the development of AI City",
  "replacement": "• Customer Collaboration: Collaborated with customers...",
  "match_type": "add_after"
}

// ❌ 错误示例（缺少 • 符号）
{
  "replacement": "Customer Collaboration: Collaborated with customers..."
}
```

**系统会自动：**
- 移除文本中的 `•` 符号
- 应用 Word 的原生 bullet 格式（缩进、间距、编号属性）
- 确保与现有 bullets 格式一致

**为什么这样设计？**
- AI 生成的内容更自然（看起来像正常的 bullet point）
- 避免双重 bullet（Word 格式 + 文本符号）
- 保持格式一致性

---

### 2. add_after 的 Target 选择（最佳实践）

**推荐：使用该 section 第一个 bullet 的开头文字作为 anchor**

```json
// ✅ 最佳实践 - 使用第一个 bullet 作为 anchor
{
  "target": "Led the development of AI City",
  "replacement": "• Customer Collaboration: Collaborated directly with customers...",
  "match_type": "add_after"
}
// 结果：新 bullet 会添加在该 section 所有 bullets 之后

// ⚠️ 可以工作但位置可能不准确
{
  "target": "Z. AI",  // 使用公司名
  "match_type": "add_after"
}
// 问题：可能会插入在公司名后、第一个 bullet 之前
```

**为什么使用 bullet 文本而非公司名？**
1. **更精确**：系统会检测连续的 bullets，插入在最后一个 bullet 之后
2. **位置正确**：确保新 bullet 与现有 bullets 在一起
3. **格式一致**：新 bullet 会复制现有 bullet 的格式（缩进、字体等）

---

### 3. replace_paragraph 使用技巧

**用于重写整个 bullet 或段落**

```json
{
  "target": "Built backend infrastructure",  // 该 bullet 的关键短语
  "replacement": "• Cloud-Native DevOps & Service Delivery: Built backend infrastructure with FastAPI and authored comprehensive technical documentation...",
  "match_type": "replace_paragraph"
}
```

**要点：**
- target 应该是该 bullet/段落中**独特的**关键短语
- replacement 写完整的新内容
- 也要包含 `•` 符号

---

## 📋 完整示例

### 场景：针对 AI Solutions Engineer 职位优化简历

```json
{
  "company_name": "TechCorp",
  "job_title": "AI Solutions Engineer",
  "job_summary": "Seeking expert in Multi-Agent Systems and Graph RAG with customer-facing experience",
  "modifications": [
    {
      "target": "Led the development of AI City",
      "replacement": "• Customer Collaboration: Collaborated directly with customers to gather requirements, co-design prototypes, and run iterative user tests, refining the platform for 50+ enterprise agents.",
      "reason": "Add new bullet addressing JD requirement for customer-facing requirement gathering with concrete metric",
      "priority": "high",
      "match_type": "add_after"
    },
    {
      "target": "Built backend infrastructure",
      "replacement": "• Cloud-Native DevOps & Service Delivery: Built backend infrastructure with FastAPI and authored comprehensive technical documentation, successfully handing over prototypes and runbooks to ops teams and customers.",
      "reason": "Rewrite bullet to demonstrate service-oriented support skills required by JD",
      "priority": "medium",
      "match_type": "replace_paragraph"
    },
    {
      "target": "Berlin, Germany",
      "replacement": "Shanghai, China",
      "reason": "Job location is Shanghai, update to match",
      "priority": "high",
      "match_type": "fuzzy"
    }
  ],
  "suggestions": [
    "Consider adding English proficiency level for customer-facing role"
  ],
  "match_score": 85
}
```

---

## 🎯 Target 选择指南

### ✅ 好的 Target 示例

| Match Type | Target | 说明 |
|------------|--------|------|
| fuzzy | `"Berlin, Germany"` | 独特的位置信息 |
| fuzzy | `"Developed ML models"` | 具体的短语 |
| add_after | `"Led the development of AI City"` | 该 section 第一个 bullet（最佳） |
| add_after | `"Architected core intelligence layer"` | 特定 bullet 内容 |
| replace_paragraph | `"Built backend infrastructure"` | bullet 的关键短语 |

### ❌ 不好的 Target 示例

| Target | 问题 |
|--------|------|
| `"Python"` | 太短，可能出现多次 |
| `"Z. AI, Beijing, China | Core developer..."` | 太长，可能不完全匹配 |
| `"Add this new bullet"` | 不是简历中的实际文本 |
| `"The DevOps bullet under DataGrand"` | 这是描述，不是实际文本 |

---

## 🔧 测试和调试

### 1. 运行测试

```bash
cd "Word Editor"
python test_user_instructions.py
```

### 2. 检查结果

- 查看 `output/Modified_Resume_Test.docx`
- 查看 `output/Modified_Resume_Test.pdf`

### 3. 常见问题

**问题：双重 bullet（• •）**
- 原因：旧版本没有移除 replacement 中的 bullet 符号
- 解决：已修复，系统会自动移除

**问题：新 bullet 位置不对**
- 原因：使用公司名作为 target
- 解决：使用该 section 第一个 bullet 的文本作为 target

**问题：新 bullet 格式不对（缩进、字体）**
- 原因：旧版本没有复制格式
- 解决：已修复，`_create_paragraph_with_formatting()` 会复制所有格式属性

---

## 🚀 启动完整系统

### 1. 启动后端服务

```bash
cd "Word Editor"
python -m resume_modifier.api_server
```

服务将运行在 `http://localhost:8000`

### 2. 刷新浏览器扩展

1. 打开 `edge://extensions/`
2. 找到 "Resume AI Editor"
3. 点击刷新按钮

### 3. 使用流程

1. 打开岗位描述页面
2. 点击扩展图标
3. 点击 "Optimize Resume"
4. 等待处理完成
5. 查看 History 下载修改后的简历

---

## 📝 AI Prompt 更新要点

已更新 `ai_analyzer.py` 的 SYSTEM_PROMPT，关键改进：

1. **明确 bullet 符号要求**
   - 添加专门章节说明必须包含 `•` 符号
   - 解释系统自动处理机制

2. **add_after 最佳实践**
   - 强调使用第一个 bullet 作为 anchor
   - 说明为什么这样更准确

3. **更新示例**
   - 所有 add_after 和 replace_paragraph 示例都包含 `•`
   - 展示正确的 target 选择方式

4. **错误示例**
   - 明确标注缺少 bullet 符号的错误示例
   - 展示常见的 target 选择错误

---

## 📚 技术细节

### Bullet 格式处理流程

```python
# content_modifier.py 中的处理逻辑

def _create_paragraph_with_formatting(self, source_para, text):
    # 1. 检测并移除 bullet 符号
    if text.strip().startswith(('•', '-', '*', '○', '▪')):
        cleaned_text = text.strip()[1:].lstrip()
    
    # 2. 复制源段落的格式属性
    - 段落属性 (pPr): 缩进、间距、bullet 编号
    - 运行属性 (rPr): 字体、大小、颜色
    
    # 3. 创建新段落，使用清理后的文本
    return new_paragraph_with_formatting
```

### add_after 位置检测

```python
# 检测连续的 bullets
insert_after_index = i  # 初始位置
for j in range(i + 1, len(paragraphs)):
    next_para = paragraphs[j]
    if next_para.text.strip().startswith(('•', '-', '*')):
        insert_after_index = j  # 更新到最后一个 bullet
    else:
        break  # 遇到非 bullet，停止
```

---

## ⚙️ 配置文件

### config.py

```python
OPENAI_API_KEY = "your-api-key"
OPENAI_MODEL = "gpt-4"
OPENAI_BASE_URL = "https://api.openai.com/v1"  # 可选

RESUME_PATH = r"C:\path\to\your\resume.docx"
```

### .env (可选)

```
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-4
```

---

## 🐛 故障排除

### 后端健康检查失败
- 检查服务是否运行：`http://localhost:8000/health`
- 查看终端错误信息
- 重启服务

### 修改未生效
- 检查 target 是否精确匹配简历中的文本
- 使用 fuzzy match_type 提高匹配成功率
- 查看 console 中的错误日志

### PDF 导出失败
- 确保安装了 `docx2pdf`：`pip install docx2pdf`
- Windows 需要 Microsoft Word
- 检查文件权限

---

## 📞 支持

如有问题，请检查：
1. 终端中的错误信息
2. 浏览器 Console 中的日志
3. `output/` 目录中的输出文件

