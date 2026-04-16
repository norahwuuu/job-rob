from docx import Document

doc = Document('cv.docx')

print("=== 检查 DataGrand 和 Z.AI 区域的 runs 格式 ===\n")

for i, para in enumerate(doc.paragraphs[:40]):
    text = para.text.strip()
    
    # 检查包含关键词的段落
    if any(keyword in text for keyword in ['DataGrand', 'Z. AI', 'Cloud-Native', 'Led the development']):
        print(f"\n段落 {i}: '{text[:60]}...'")
        print(f"  总 Runs: {len(para.runs)}")
        
        # 显示每个 run 的详细格式
        for j, run in enumerate(para.runs):
            print(f"  Run {j}: '{run.text}'")
            print(f"    Bold: {run.bold}")
            print(f"    Italic: {run.italic}")
            print(f"    Font name: {run.font.name}")
            print(f"    Font size: {run.font.size}")
            if hasattr(run._element, 'rPr') and run._element.rPr is not None:
                print(f"    Has rPr: Yes")
            else:
                print(f"    Has rPr: No")
