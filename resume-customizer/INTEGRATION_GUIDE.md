# resume-customizer integration guide

用于对接浏览器插件与 `word_editor` 后端。

## 前置条件

- Python 3.10+
- `resume-customizer/word_editor/.env` 已配置：
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
  - `OPENAI_BASE_URL`（可选）

## 启动后端

```bash
cd "resume-customizer/word_editor"
python -m pip install -r requirements.txt
python -m resume_modifier.api_server
```

默认地址：`http://127.0.0.1:8000`

## 插件对接

1. 打开浏览器扩展管理页面。
2. 开启开发者模式。
3. 加载目录 `resume-customizer/web-to-pdf-plugin/web-to-md-pdf-plugin`。
4. 在招聘页面点击插件，触发简历优化请求。

## 最小联调检查

- `GET /api/health` 返回成功。
- 插件触发后可看到任务状态和下载链接。
- `word_editor/output/` 中产生对应任务文件。

## 文档入口

- 统一使用与故障排查：`HANDBOOK.md`
- 子项目职责与本地运行：`word_editor/README.md`
