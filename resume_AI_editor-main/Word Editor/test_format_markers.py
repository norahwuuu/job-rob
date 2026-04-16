"""
测试格式标记功能
"""
from resume_modifier.content_modifier import ContentModifier, ModificationInstruction

# 测试指令
instructions = [
    ModificationInstruction(
        target="Led the development of AI City",
        replacement="• Customer Collaboration: Collaborated directly with **customers** to gather *requirements*, co-design **prototypes**, and run iterative user tests.",
        reason="Test format markers: customers and prototypes in bold, requirements in italic",
        priority="high",
        match_type="add_after"
    ),
    ModificationInstruction(
        target="Built backend infrastructure",
        replacement="• Cloud-Native DevOps: Built backend infrastructure with **FastAPI** and authored comprehensive *technical documentation*, successfully handing over **prototypes** to ops teams.",
        reason="Test format markers in replace_paragraph",
        priority="medium",
        match_type="replace_paragraph"
    )
]

print("=" * 70)
print("测试格式标记功能")
print("=" * 70)
print("\n格式标记说明：")
print("  **text** → 加粗")
print("  *text*   → 斜体")
print("  普通文本 → 正常\n")

modifier = ContentModifier("cv.docx")

print("应用修改...")
success_count = modifier.apply_modifications(instructions)

print(f"\n成功应用: {success_count}/{len(instructions)}\n")

# 显示日志
for log in modifier.logs:
    status = "✅" if log.success else "❌"
    print(f"{status} {log.target[:50]}")
    if log.success:
        print(f"   位置: {log.location}")
    else:
        print(f"   错误: {log.error_message}")

# 保存
output_path = "output/Modified_Resume_Format_Test.docx"
modifier.save(output_path)
print(f"\n💾 已保存: {output_path}")

# 导出 PDF
from resume_modifier.pdf_exporter import export_to_pdf
pdf_path = export_to_pdf(output_path, "output")
print(f"📄 已导出: {pdf_path}")

print("\n🎯 请打开文件检查格式：")
print("   - 'customers', 'prototypes', 'FastAPI' 应该是加粗")
print("   - 'requirements', 'technical documentation' 应该是斜体")
print("   - 其他文本应该是正常格式")
