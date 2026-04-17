"""Test resume parser"""
from resume_modifier.resume_parser import parse_resume

try:
    result = parse_resume('cv.docx')
    print("Parse successful!")
    print(f"Text blocks: {len(result.all_blocks)}")
    print(f"Tables: {len(result.tables)}")
    print(f"\nPreview (first 500 chars):")
    print("-" * 50)
    # Encode to ascii with replace for terminal compatibility
    preview = result.full_text[:500].encode('ascii', 'replace').decode('ascii')
    print(preview)
    print("-" * 50)
except Exception as e:
    print(f"Parse failed: {e}")
    import traceback
    traceback.print_exc()
