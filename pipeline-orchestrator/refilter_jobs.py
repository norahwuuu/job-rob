#!/usr/bin/env python3
"""重新筛选'AI未返回结果，默认保留'的岗位"""

import json
import re

# AI相关关键词（保留）
AI_KEYWORDS = [
    r'\bai\b', r'\bml\b', r'\bllm\b', r'\bgpt\b', r'\bgenai\b', r'\bgen ai\b',
    r'machine learning', r'deep learning', r'neural', r'nlp', r'data scien',
    r'artificial intelligence', r'\bki\b', r'künstliche intelligenz',
    r'robotics', r'computer vision', r'autonomous', r'agent', r'rag\b',
    r'langchain', r'langgraph', r'transformer', r'embedding', r'vector',
    r'chatbot', r'conversational', r'recommendation', r'prompt engineer',
]

# 明确不相关的岗位类型（过滤掉）
EXCLUDE_TITLES = [
    r'ceo\b', r'cto\b', r'cfo\b', r'coo\b',  # C-level
    r'\bsales\b', r'account\s*manager', r'business\s*develop',  # 销售
    r'\bhr\b', r'human\s*resource', r'recruiter', r'talent\s*acqui',  # HR
    r'marketing\s*(manager|director|lead)', r'brand\s*manager',  # 市场营销管理
    r'legal', r'lawyer', r'rechtsanwalt', r'counsel',  # 法务
    r'accountant', r'financial\s*analyst', r'tax\b', r'steuer',  # 财务
    r'project\s*manager', r'program\s*manager', r'scrum\s*master',  # 项目管理（非技术）
    r'customer\s*success', r'customer\s*support', r'support\s*specialist',  # 客服
    r'phd\b', r'doktor', r'doctoral', r'dissertation',  # 博士生
    r'intern\b', r'praktik', r'werkstudent', r'working\s*student', r'ausbildung',  # 实习/学生
    r'junior\b',  # 初级
    r'designer', r'ui/ux', r'ux/ui', r'graphic',  # 设计
    r'analog\s*design', r'hardware\s*engineer', r'electrical\s*engineer',  # 硬件
    r'mechanical\s*engineer', r'production\s*engineer',  # 机械/生产
    r'venture\s*manager', r'investment', r'private\s*equity',  # 投资
    r'security\s*operations', r'soc\s*analyst', r'it\s*audit',  # 安全运维
    r'erp\b', r'sap\b',  # ERP/SAP（非AI）
    r'freelance', r'contractor',  # 自由职业
]

# 明确不相关的公司（黑名单）
# 已清空黑名单：不过滤任何公司
EXCLUDE_COMPANIES = []

# 知名AI公司白名单（直接通过）
AI_COMPANIES = [
    r'openai', r'anthropic', r'deepmind', r'google\s*deepmind',
    r'mistral', r'cohere', r'stability\s*ai', r'hugging\s*face',
    r'perplexity', r'deepl', r'scale\s*ai', r'databricks',
    r'nvidia', r'langchain', r'pinecone', r'weaviate',
]

def should_keep(job):
    """判断岗位是否应该保留"""
    title = job.get('title', '').lower()
    company = job.get('company', '').lower()
    description = job.get('job_description', '').lower()
    
    # 0. 检查是否是知名AI公司
    for pattern in AI_COMPANIES:
        if re.search(pattern, company, re.IGNORECASE):
            return True, f"知名AI公司: {company}"
    
    # 1. 检查公司黑名单
    for pattern in EXCLUDE_COMPANIES:
        if re.search(pattern, company, re.IGNORECASE):
            return False, f"公司在黑名单: {company}"
    
    # 2. 检查标题是否明确不相关
    for pattern in EXCLUDE_TITLES:
        if re.search(pattern, title, re.IGNORECASE):
            return False, f"岗位类型不符: {pattern}"
    
    # 3. 检查标题或描述是否包含AI相关关键词
    for pattern in AI_KEYWORDS:
        if re.search(pattern, title, re.IGNORECASE):
            return True, f"标题包含AI关键词: {pattern}"
        if re.search(pattern, description[:500], re.IGNORECASE):  # 只检查前500字符
            return True, f"描述包含AI关键词: {pattern}"
    
    # 4. 如果是纯后端/前端/全栈，且没有AI关键词，过滤掉
    generic_dev = [r'backend', r'frontend', r'full\s*stack', r'software\s*engineer', 
                   r'developer', r'entwickler', r'cloud\s*engineer', r'devops']
    for pattern in generic_dev:
        if re.search(pattern, title, re.IGNORECASE):
            return False, f"通用开发岗位无AI关键词: {pattern}"
    
    # 5. 默认过滤（保守策略）
    return False, "未发现AI相关属性"


def main():
    with open('jobs_progress.json', 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    # 找出所有'AI未返回结果，默认保留'的岗位
    unfiltered_indices = []
    for i, job in enumerate(jobs):
        if job.get('ai_reason', '').endswith('AI未返回结果，默认保留'):
            unfiltered_indices.append(i)
    
    print(f"共有 {len(unfiltered_indices)} 个需要重新筛选的岗位\n")
    
    kept = 0
    filtered = 0
    
    for idx in unfiltered_indices:
        job = jobs[idx]
        title = job.get('title', '')
        company = job.get('company', '')
        
        keep, reason = should_keep(job)
        
        if keep:
            jobs[idx]['passed_filter'] = True
            jobs[idx]['ai_reason'] = f"[重新筛选] ✓ {reason}"
            jobs[idx]['ai_score'] = 50.0  # 给一个中等分数
            kept += 1
            print(f"✓ 保留: {title} @ {company}")
            print(f"  原因: {reason}\n")
        else:
            jobs[idx]['passed_filter'] = False
            jobs[idx]['ai_reason'] = f"[重新筛选] ✗ {reason}"
            jobs[idx]['ai_score'] = 0.0
            filtered += 1
            print(f"✗ 过滤: {title} @ {company}")
            print(f"  原因: {reason}\n")
    
    # 保存修改
    with open('jobs_progress.json', 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    
    print("=" * 60)
    print(f"重新筛选完成:")
    print(f"  保留: {kept} 个")
    print(f"  过滤: {filtered} 个")
    print(f"已保存到 jobs_progress.json")


if __name__ == '__main__':
    main()
