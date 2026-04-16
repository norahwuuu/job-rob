"""
快速测试脚本 - 验证优化后的输出刷新
"""
import sys
sys.stdout.reconfigure(line_buffering=True)  # 确保行缓冲

from resume_modifier.content_modifier import ContentModifier, ModificationInstruction

print("="*70, flush=True)
print("测试实时输出刷新", flush=True)
print("="*70, flush=True)

# 简单的测试指令
instructions = [
    ModificationInstruction(
        target="Berlin, Germany",
        replacement="Shanghai, China",
        reason="测试快速修改",
        priority="high",
        match_type="fuzzy"
    ),
    ModificationInstruction(
        target="AI & GenAI: Multi-Agent Systems",
        replacement="AI & GenAI: **Multi-Agent Systems**, **Simulation Automation**",
        reason="测试格式标记",
        priority="medium",
        match_type="fuzzy"
    )
]

print("\n创建修改器...", flush=True)
modifier = ContentModifier("cv.docx")

print("应用修改...\n", flush=True)
success_count = modifier.apply_modifications(instructions)

print(f"\n完成! 成功: {success_count}/{len(instructions)}\n", flush=True)

# 保存
output_path = "output/Quick_Test.docx"
modifier.save(output_path)
print(f"💾 已保存: {output_path}", flush=True)

print("\n✅ 测试完成 - 检查输出是否实时显示", flush=True)
