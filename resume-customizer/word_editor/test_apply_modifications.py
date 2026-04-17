"""
测试脚本：直接应用日志中的修改指令，不调用AI
"""
import json
from pathlib import Path
from resume_modifier.resume_parser import ResumeParser
from resume_modifier.content_modifier import ContentModifier, ModificationInstruction

# 读取日志文件
log_path = Path("output/application_logs.json")
with open(log_path, 'r', encoding='utf-8') as f:
    logs = json.load(f)

# 获取最后一次的任务
last_task = logs[-1]
print(f"公司: {last_task['company_name']}")
print(f"职位: {last_task['job_title']}")
print(f"原匹配度: {last_task['match_score']}%")
print(f"修改指令: {len(last_task['modifications'])} 条")
print(f"原成功: {last_task['success_count']}/{last_task['total_count']}")
print("\n" + "="*70 + "\n")

# 加载原始简历
resume_path = Path("cv.docx")
print(f"📄 加载简历: {resume_path}")

# 解析简历
parser = ResumeParser(str(resume_path))
parsed = parser.parse()
print(f"✓ 解析完成，共 {len(parsed.all_blocks)} 个文本块\n")

# 创建修改器
modifier = ContentModifier(str(resume_path))

# 转换日志中的修改指令
instructions = []
for mod in last_task['modifications']:
    instructions.append(ModificationInstruction(
        target=mod['target'],
        replacement=mod['replacement'],
        reason=mod['reason'],
        priority='high'
    ))

print(f"🔧 应用 {len(instructions)} 条修改指令...\n")

# 应用修改
success_count = modifier.apply_modifications(instructions)

print(f"\n✨ 完成! 成功应用 {success_count}/{len(instructions)} 条修改\n")

# 显示失败的修改
failed_logs = [log for log in modifier.logs if not log.success]
if failed_logs:
    print(f"⚠ {len(failed_logs)} 处修改未能应用:")
    for log in failed_logs:
        print(f"  - 目标: '{log.target[:60]}...'")
        print(f"    错误: {log.error_message}\n")
else:
    print("✅ 所有修改都成功应用!")

# 保存测试结果
output_path = Path("output/test_modifications_result.docx")
output_path.parent.mkdir(parents=True, exist_ok=True)
modifier.save(str(output_path))
print(f"\n💾 已保存到: {output_path}")
