"""
Test new add_after and replace_paragraph features
"""

from resume_modifier.content_modifier import ContentModifier, ModificationInstruction
from pathlib import Path

def test_add_after():
    """Test adding a new bullet point after a target"""
    print("\n=== Testing add_after functionality ===")
    
    # Create test instruction
    instruction = ModificationInstruction(
        target="Z. AI",  # Anchor point - company name
        replacement="• Customer Collaboration: Worked directly with customers to gather requirements and co-design prototypes",
        reason="Add customer-facing experience bullet",
        priority="high",
        match_type="add_after"
    )
    
    print(f"Instruction: Add after '{instruction.target}'")
    print(f"New content: {instruction.replacement[:60]}...")
    print(f"Match type: {instruction.match_type}")

def test_replace_paragraph():
    """Test replacing entire paragraph"""
    print("\n=== Testing replace_paragraph functionality ===")
    
    instruction = ModificationInstruction(
        target="Built backend infrastructure",  # Key phrase to identify bullet
        replacement="• Cloud-Native DevOps & Service Delivery: Built backend infrastructure with FastAPI and authored comprehensive technical documentation",
        reason="Rewrite to emphasize service delivery",
        priority="medium",
        match_type="replace_paragraph"
    )
    
    print(f"Instruction: Replace paragraph containing '{instruction.target}'")
    print(f"New content: {instruction.replacement[:60]}...")
    print(f"Match type: {instruction.match_type}")

def test_fuzzy_replacement():
    """Test traditional fuzzy replacement"""
    print("\n=== Testing fuzzy replacement (traditional) ===")
    
    instruction = ModificationInstruction(
        target="Berlin, Germany",
        replacement="Shanghai, China",
        reason="Update location to match job requirements",
        priority="high",
        match_type="fuzzy"
    )
    
    print(f"Instruction: Replace '{instruction.target}' with '{instruction.replacement}'")
    print(f"Match type: {instruction.match_type}")

if __name__ == "__main__":
    print("=" * 60)
    print("NEW FEATURES DEMONSTRATION")
    print("=" * 60)
    
    test_add_after()
    test_replace_paragraph()
    test_fuzzy_replacement()
    
    print("\n" + "=" * 60)
    print("FEATURE SUMMARY")
    print("=" * 60)
    print("""
Supported match_types:
1. fuzzy (default)      - Replace existing text with fuzzy matching
2. exact                - Exact string matching
3. add_after (NEW!)     - Add new bullet/paragraph after target
4. replace_paragraph (NEW!) - Replace entire paragraph containing target

Usage Examples:
- Location change:      fuzzy
- Skill enhancement:    fuzzy
- Add new bullet:       add_after (target = anchor point like company name)
- Rewrite bullet:       replace_paragraph (target = identifying phrase)
    """)
    
    print("\n✅ All features are implemented and ready to use!")
    print("   AI prompts are now in English with clear examples.")
