"""
Test user's modification instructions
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from resume_modifier.content_modifier import ContentModifier, ModificationInstruction
from resume_modifier.pdf_exporter import export_to_pdf

def test_user_instructions():
    """Test the user's modification instructions"""
    
    # Original instructions with match_type converted
    instructions_data = {
        "company_name": "Target Company (Inferred)",
        "job_title": "AI Solutions Engineer / Full-Stack AI Architect",
        "job_summary": "Expert in Multi-Agent Systems and Graph RAG, seeking to leverage experience in customer-facing requirement gathering and documented prototype delivery.",
        "modifications": [
            {
                "target": "Led the development of AI City",  # Changed: use first bullet as anchor
                "replacement": "• Customer Collaboration: Collaborated directly with customers to gather requirements and co-design prototypes, running iterative user tests that refined the platform for 50+ enterprise agents.",
                "reason": "Add this new bullet point under the 'Z. AI' role. It explicitly addresses the requirement for 'gathering requirements, co-designing prototypes, and running iterative user tests' with a concrete metric (50+ agents), balancing your technical profile with product skills.",
                "priority": "high",
                "match_type": "add_after"  # Will insert after all bullets in this section
            },
            {
                "target": "Cloud-Native DevOps",  # Changed: use identifying phrase from the bullet
                "replacement": "• Cloud-Native DevOps & Service Delivery: Built backend infrastructure with FastAPI and authored comprehensive technical documentation, successfully handing over prototypes and runbooks to ops teams and customers.",
                "reason": "Rewrite the 'Cloud-Native DevOps' bullet under DataGrand. By appending the 'documented prototypes and handed over' part here, you demonstrate the service-oriented support skills required by the JD without removing your technical DevOps achievements.",
                "priority": "medium",
                "match_type": "replace_paragraph"  # Changed from "rewrite_bullet_point"
            }
        ],
        "suggestions": [
            "Critical Typo: Your GreenZero start date is listed as 'Sep 2025' (future date). Please correct this to the actual date (e.g., Sep 2024) to avoid rejection by ATS parsers.",
            "Language: For customer-facing roles in Germany, consider specifying if English was the primary language for your previous client interactions to mitigate concerns about the A2 German level."
        ],
        "match_score": 85
    }
    
    print("=" * 70)
    print("TESTING USER INSTRUCTIONS")
    print("=" * 70)
    print(f"\nCompany: {instructions_data['company_name']}")
    print(f"Job Title: {instructions_data['job_title']}")
    print(f"Match Score: {instructions_data['match_score']}%")
    print(f"\nJob Summary: {instructions_data['job_summary']}")
    
    # Resume path
    resume_path = Path("cv.docx")
    if not resume_path.exists():
        print(f"\n❌ Resume not found: {resume_path}")
        return
    
    print(f"\n📄 Resume: {resume_path}")
    
    # Create modifier
    modifier = ContentModifier(str(resume_path))
    
    # Convert to ModificationInstruction objects
    instructions = []
    print("\n" + "=" * 70)
    print("MODIFICATIONS TO APPLY")
    print("=" * 70)
    
    for i, mod_data in enumerate(instructions_data['modifications'], 1):
        print(f"\n{i}. [{mod_data['priority'].upper()}] {mod_data['match_type']}")
        print(f"   Target: {mod_data['target'][:60]}...")
        print(f"   Replacement: {mod_data['replacement'][:60]}...")
        print(f"   Reason: {mod_data['reason'][:80]}...")
        
        instruction = ModificationInstruction(
            target=mod_data['target'],
            replacement=mod_data['replacement'],
            reason=mod_data['reason'],
            priority=mod_data['priority'],
            match_type=mod_data['match_type']
        )
        instructions.append(instruction)
    
    # Apply modifications
    print("\n" + "=" * 70)
    print("APPLYING MODIFICATIONS...")
    print("=" * 70)
    
    success_count = modifier.apply_modifications(instructions)
    
    # Show results
    print(f"\n✅ Successfully applied: {success_count}/{len(instructions)}")
    
    print("\n" + "=" * 70)
    print("MODIFICATION LOG")
    print("=" * 70)
    
    for i, log in enumerate(modifier.logs, 1):
        status = "✅ SUCCESS" if log.success else "❌ FAILED"
        print(f"\n{i}. {status}")
        print(f"   Target: {log.target[:60]}")
        print(f"   Location: {log.location}")
        if log.success:
            print(f"   Replacement: {log.replacement[:60]}...")
        else:
            print(f"   Error: {log.error_message}")
    
    # Save modified document
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    output_docx = output_dir / "Modified_Resume_Test.docx"
    modifier.save(str(output_docx))
    print(f"\n💾 Saved modified Word: {output_docx}")
    
    # Export to PDF
    output_pdf = output_dir / "Modified_Resume_Test.pdf"
    try:
        export_to_pdf(str(output_docx), str(output_pdf))
        print(f"📄 Exported PDF: {output_pdf}")
        print(f"\n🎯 Open this file to see the results!")
    except Exception as e:
        print(f"⚠️  PDF export failed: {e}")
        print(f"   You can manually open the Word file: {output_docx}")
    
    # Show suggestions
    if instructions_data['suggestions']:
        print("\n" + "=" * 70)
        print("AI SUGGESTIONS (not applied)")
        print("=" * 70)
        for i, suggestion in enumerate(instructions_data['suggestions'], 1):
            print(f"{i}. {suggestion}")
    
    print("\n" + "=" * 70)
    print(f"✅ TEST COMPLETE - Check: {output_pdf}")
    print("=" * 70)

if __name__ == "__main__":
    test_user_instructions()
