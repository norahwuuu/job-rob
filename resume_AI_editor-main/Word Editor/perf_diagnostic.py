"""
性能诊断脚本 - 测量每个步骤的耗时
模拟完整流程，找出瓶颈
"""
import time
import sys
sys.stdout.reconfigure(line_buffering=True)

from pathlib import Path

print("=" * 70)
print("🔍 性能诊断开始")
print("=" * 70)

# 测试1: 简历解析
print("\n📖 步骤1: 简历解析...")
start = time.time()
from resume_modifier.resume_parser import ResumeParser
parser = ResumeParser("cv.docx")
parsed = parser.parse()
resume_text = parser.get_text_for_ai()
parse_time = time.time() - start
print(f"   ⏱️ 耗时: {parse_time:.2f}秒")

# 测试2: AI 分析（这通常是最慢的）
print("\n🤖 步骤2: AI 分析...")
start = time.time()
from resume_modifier.ai_analyzer import AIAnalyzer
analyzer = AIAnalyzer()

# 简短的测试JD
test_jd = """
Software Engineer - AI/ML
Requirements:
- Python, TypeScript
- Experience with LLMs, RAG systems
- Cloud deployment (AWS/Azure)
"""

analysis = analyzer.analyze(test_jd, resume_text)
ai_time = time.time() - start
print(f"   ⏱️ 耗时: {ai_time:.2f}秒")
print(f"   📝 生成了 {len(analysis.modifications)} 条修改指令")

# 测试3: 文档修改
print("\n📝 步骤3: 文档修改...")
start = time.time()
from resume_modifier.content_modifier import ContentModifier, ModificationInstruction

modifier = ContentModifier("cv.docx")

# 只取前2条指令测试
test_instructions = []
for m in analysis.modifications[:2]:
    test_instructions.append(ModificationInstruction(
        target=m.target,
        replacement=m.replacement,
        reason=m.reason,
        priority=m.priority,
        match_type=m.match_type
    ))

success_count = modifier.apply_modifications(test_instructions)
modify_time = time.time() - start
print(f"   ⏱️ 耗时: {modify_time:.2f}秒 (2条指令)")
print(f"   ✅ 成功: {success_count}/2")

# 测试4: 保存文档
print("\n💾 步骤4: 保存 Word...")
start = time.time()
output_path = "output/Perf_Test.docx"
Path("output").mkdir(exist_ok=True)
modifier.save(output_path)
save_time = time.time() - start
print(f"   ⏱️ 耗时: {save_time:.2f}秒")

# 测试5: PDF 导出
print("\n📄 步骤5: PDF 导出...")
start = time.time()
from resume_modifier.pdf_exporter import PDFExporter
exporter = PDFExporter()
pdf_path = exporter.convert(output_path, "output/Perf_Test.pdf")
pdf_time = time.time() - start
print(f"   ⏱️ 耗时: {pdf_time:.2f}秒")

# 总结
print("\n" + "=" * 70)
print("📊 性能总结")
print("=" * 70)
print(f"   简历解析:  {parse_time:.2f}秒")
print(f"   AI 分析:   {ai_time:.2f}秒  {'⚠️ 较慢' if ai_time > 10 else '✅'}")
print(f"   文档修改:  {modify_time:.2f}秒 (2条)  {'⚠️ 较慢' if modify_time > 5 else '✅'}")
print(f"   保存文档:  {save_time:.2f}秒")
print(f"   PDF导出:   {pdf_time:.2f}秒  {'⚠️ 较慢' if pdf_time > 5 else '✅'}")
print("-" * 70)
total = parse_time + ai_time + modify_time + save_time + pdf_time
print(f"   总计:      {total:.2f}秒")

if modify_time > 5:
    print("\n⚠️ 文档修改异常慢，需要进一步检查：")
    print("   - 检查是否有死循环")
    print("   - 检查是否有阻塞操作")
    print("   - 检查文档解析效率")

print("\n✅ 诊断完成")
