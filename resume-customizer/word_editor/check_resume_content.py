"""
Check resume content to find correct target text
"""
from docx import Document

doc = Document('cv.docx')

print("=" * 70)
print("RESUME CONTENT - Looking for company names")
print("=" * 70)

for i, para in enumerate(doc.paragraphs):
    text = para.text.strip()
    if text and any(keyword in text for keyword in ['AI', 'DataGrand', 'Greenzero', 'DevOps']):
        print(f"\nParagraph {i}:")
        print(f"  Text: {text[:100]}")
        print(f"  Length: {len(text)} chars")
