"""
测试格式标记修复
验证 **bold** 和 *italic* 标记是否正确解析和应用
"""
import sys
from pathlib import Path
from resume_modifier.content_modifier import ContentModifier, ModificationInstruction

def test_format_markers():
    """测试格式标记是否正确应用"""
    
    # 使用测试简历
    resume_path = r"./cv.docx"
    
    if not Path(resume_path).exists():
        print(f"❌ 简历文件不存在: {resume_path}")
        return
    
    print("📄 加载简历...")
    modifier = ContentModifier(resume_path)
    
    # 测试1: 简单的bold替换
    print("\n🧪 测试 1: 替换文本并添加粗体")
    instruction = ModificationInstruction(
        target="LLM API integrations",
        replacement="**LLM API integrations** and **prompt engineering**",
        reason="测试粗体标记",
        match_type="fuzzy"
    )
    
    result = modifier._apply_single_modification(instruction)
    print(f"   结果: {'✅ 成功' if result else '❌ 失败'}")
    
    # 查看实际文本
    print("\n📝 检查文档内容...")
    for para in modifier.doc.paragraphs:
        text = para.text
        if "API integrations" in text:
            print(f"   段落文本: {text[:100]}")
            print(f"   Runs 数量: {len(para.runs)}")
            for i, run in enumerate(para.runs):
                if run.text.strip():
                    print(f"     Run {i}: '{run.text}' | Bold={run.bold} | Italic={run.italic}")
    
    # 保存测试文件
    output_path = r"./output/test_format_fix.docx"
    modifier.save(output_path)
    print(f"\n✅ 测试文件已保存: {output_path}")
    print("\n请打开文件检查：")
    print("   1. 星号 ** 是否消失了？")
    print("   2. 文本是否正确加粗了？")

if __name__ == "__main__":
    test_format_markers()
