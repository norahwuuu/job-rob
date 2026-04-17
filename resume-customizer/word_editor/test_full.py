"""Full test - parse, modify, and export PDF"""
import os
from pathlib import Path

from resume_modifier.resume_parser import parse_resume
from resume_modifier.content_modifier import ContentModifier, ModificationInstruction
from resume_modifier.pdf_exporter import PDFExporter

# Output directory
OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 60)
print("Resume Auto-Modifier Test")
print("=" * 60)

# 1. Parse resume
print("\n[Step 1] Parsing resume...")
resume_path = 'cv.docx'
parsed = parse_resume(resume_path)
print(f"  - Text blocks: {len(parsed.all_blocks)}")
print(f"  - Full text length: {len(parsed.full_text)} characters")

# 2. Create test modification instructions (simulating AI output)
print("\n[Step 2] Creating modification instructions...")
instructions = [
    ModificationInstruction(
        target="Berlin, Germany",
        replacement="Beijing, China",
        reason="Job requires work experience in China",
        priority="high"
    ),
    ModificationInstruction(
        target="Location: Berlin, Germany",
        replacement="Location: Beijing, China",
        reason="Job requires work experience in China",
        priority="high"
    ),
]

for i, inst in enumerate(instructions, 1):
    print(f"  {i}. '{inst.target}' -> '{inst.replacement}'")
    print(f"     Reason: {inst.reason}")

# 3. Apply modifications
print("\n[Step 3] Applying modifications...")
modifier = ContentModifier(resume_path)
success_count = modifier.apply_modifications(instructions)
print(f"  - Successful modifications: {success_count}/{len(instructions)}")

# Show modification logs
summary = modifier.get_summary()
if summary['success_details']:
    print("\n  Successful:")
    for detail in summary['success_details']:
        print(f"    + {detail['target'][:40]}...")
if summary['failed_details']:
    print("\n  Failed:")
    for detail in summary['failed_details']:
        target = detail['target'][:40].encode('ascii', 'replace').decode('ascii')
        error = str(detail['error']).encode('ascii', 'replace').decode('ascii') if detail['error'] else 'Unknown'
        print(f"    - {target}... ({error})")

# 4. Save modified Word document
print("\n[Step 4] Saving modified Word document...")
word_output = OUTPUT_DIR / "modified_resume.docx"
modifier.save(str(word_output))
print(f"  - Saved: {word_output}")

# 5. Export to PDF
print("\n[Step 5] Exporting to PDF...")
try:
    exporter = PDFExporter()
    print(f"  - Using converter: {exporter.converter}")
    pdf_output = OUTPUT_DIR / "modified_resume.pdf"
    exporter.convert(str(word_output), str(pdf_output))
    print(f"  - Saved: {pdf_output}")
    
    # File sizes
    word_size = os.path.getsize(word_output) / 1024
    pdf_size = os.path.getsize(pdf_output) / 1024
    print(f"\n  File sizes:")
    print(f"    - Word: {word_size:.1f} KB")
    print(f"    - PDF: {pdf_size:.1f} KB")
except Exception as e:
    print(f"  - PDF export failed: {e}")
    print("  - (This is expected if Microsoft Word is not installed)")

print("\n" + "=" * 60)
print("Test completed!")
print("=" * 60)
