"""
测试自动修正功能
"""
from resume_modifier.ai_analyzer import AIAnalyzer, ModificationInstruction

# 创建测试数据 - 模拟AI返回的没有加粗前导语的指令
test_modifications = [
    ModificationInstruction(
        target="Test 1",
        replacement="• Customer Collaboration: Worked with customers...",  # 缺少加粗
        reason="Test",
        priority="high"
    ),
    ModificationInstruction(
        target="Test 2",
        replacement="AI & GenAI: Multi-Agent Systems, LangChain...",  # 缺少加粗
        reason="Test",
        priority="high"
    ),
    ModificationInstruction(
        target="Test 3",
        replacement="• **Graph RAG Development:** Led design...",  # 已经正确加粗
        reason="Test",
        priority="high"
    ),
    ModificationInstruction(
        target="Test 4",
        replacement="**Backend & Languages:** Python, TypeScript...",  # 已经正确加粗
        reason="Test",
        priority="high"
    )
]

# 创建analyzer实例
analyzer = AIAnalyzer()

# 应用自动修正
print("="*70)
print("测试自动修正功能")
print("="*70)

fixed = analyzer._auto_fix_bold_formatting(test_modifications)

for i, (original, fixed_mod) in enumerate(zip(test_modifications, fixed), 1):
    print(f"\n[{i}] 原始: {original.replacement}")
    print(f"    修正: {fixed_mod.replacement}")
    if original.replacement != fixed_mod.replacement:
        print(f"    ✅ 已自动修正!")
    else:
        print(f"    ℹ️  无需修正")

print("\n" + "="*70)
print("✅ 自动修正功能测试完成")
print("="*70)
