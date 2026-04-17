"""
调试自动修正功能
"""
replacement = "• **Graph RAG Development:** Led design..."

bullet_char = replacement[0]
content = replacement[1:].strip()
print(f"Bullet char: '{bullet_char}'")
print(f"Content: '{content}'")

colon_pos = content.find(':')
print(f"Colon position: {colon_pos}")

leading_part = content[:colon_pos].strip()
rest_part = content[colon_pos+1:]
print(f"Leading part: '{leading_part}'")
print(f"Rest part: '{rest_part}'")

print(f"Starts with **: {leading_part.startswith('**')}")
print(f"Ends with **: {leading_part.endswith('**')}")
print(f"Length: {len(leading_part)}")

# 正确的检测应该是找第一个**和最后一个**
if leading_part.startswith('**'):
    # 找到第一个**后面的内容
    after_first = leading_part[2:]
    print(f"After first **: '{after_first}'")
    if after_first.endswith('**'):
        print("✓ 格式正确!")
    else:
        print("✗ 缺少结尾**")
