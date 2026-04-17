"""
测试脚本：应用修改指令并确保前导语加粗
"""
import json
from pathlib import Path
from resume_modifier.resume_parser import ResumeParser
from resume_modifier.content_modifier import ContentModifier, ModificationInstruction

# 读取日志文件
log_path = Path("output/application_logs.json")
with open(log_path, 'r', encoding='utf-8') as f:
    logs = json.load(f)

# 获取最后一次的任务
last_task = logs[-1]
print(f"公司: {last_task['company_name']}")
print(f"职位: {last_task['job_title']}")
print(f"原匹配度: {last_task['match_score']}%")
print(f"修改指令: {len(last_task['modifications'])} 条")
print("\n" + "="*70 + "\n")

# 手动修正replacement文本，确保前导语加粗
corrected_modifications = [
    {
        "target": "Enterprise RAG Knowledge Base & Workflow Automation: Architected a private knowledge retrieval system using RAGFlow to process heterogeneous internal data, leveraging Deep Document Understanding to successfully parse complex layouts (financial tables, scanned PDFs) where traditional OCR failed.",
        "replacement": "**Enterprise RAG & Retrieval Pipelines:** Architected private knowledge retrieval using **RAGFlow** with semantic chunking, hybrid (vector+keyword) search, and robust document parsing for complex layouts. Built retrieval pipelines with citation-grounding and HITL validation, and instrumented evaluation/monitoring to track quality and drift.",
        "reason": "Emphasize retrieval pipelines, semantic chunking, citation grounding, and monitoring/evaluation (matches JD RAG + benchmarking requirements).",
        "priority": "high"
    },
    {
        "target": "AI & GenAI: Multi-Agent Systems, RAG, Graph RAG, AI Agentic, LangChain, LangGraph, n8n workflow, Prompt Engineering, Semantic Search, MCP (Model Context Protocol).",
        "replacement": "**AI & GenAI:** Multi-Agent Systems, **LLM API integrations**, RAG/RAGFlow, Graph RAG, AI Agentic, **LangChain**, LangGraph, n8n workflows, Prompt Engineering, Semantic Search, MCP (Model Context Protocol).",
        "reason": "Make LLM API experience explicit (core JD requirement) and call out RAGFlow to match retrieval pipeline expectations.",
        "priority": "high"
    },
    {
        "target": "Backend & Languages: Python, TypeScript, Java, FastAPI, Next.js, SQL/NoSQL, RESTful APIs, GraphQL, Vector DBs.",
        "replacement": "**Backend & Languages:** **Python** (FastAPI), **TypeScript**, Java, Next.js, SQL/NoSQL, RESTful & streaming LLM APIs, GraphQL, Vector DBs, agent-orchestration libraries.",
        "reason": "Emphasize FastAPI + streaming LLM APIs and agent orchestration to match Wolters Kluwer's backend + LLM integration requirements.",
        "priority": "high"
    },
    {
        "target": "Leading the architecture and development of the \"Horus Platform,\" an enterprise CRM and automation system for the ecological credits market",
        "replacement": "**Platform & LLM Integrations:** Led architecture and development of the \"Horus Platform,\" designing **FastAPI** backends and **LLM API** integrations to power chat-based UX, RAG-backed knowledge, and secure agent orchestration for enterprise CRM in the ecological credits market.",
        "reason": "Rewrite to explicitly call out FastAPI, LLM APIs, chat UX, and agent orchestration—key responsibilities from the JD.",
        "priority": "high"
    },
    {
        "target": "Led the development of AI City using TypeScript, evolving pure LLMs into a visualized multi-agent simulation platform with integrated RAG knowledge bases  and human users through chatbot interfaces.",
        "replacement": "**Product & Agent Orchestration:** Built chat-based interfaces and LLM API orchestration (tool routing, parallel agent execution) and integrated backend services (FastAPI) for multi-step agent workflows; collaborated with Product and Design to prototype, test and refine user flows.",
        "reason": "Add a product-facing bullet describing chat UX, LLM API orchestration, and cross-functional collaboration to match the JD's emphasis on product & teamwork.",
        "priority": "high"
    },
    {
        "target": "Cloud & DevOps: Linux, Kubernetes (K8s), Docker, Azure, CI/CD Automation, Microservices, Hybrid-Cloud.",
        "replacement": "**Cloud & DevOps:** Linux, Kubernetes (K8s), Docker, Azure, CI/CD Automation, Observability & alerting (prometheus / **Langfuse**), Microservices, Hybrid-Cloud, security best practices.",
        "reason": "Add observability/alerting and Langfuse to align with JD requirement for evaluation/monitoring and quality assurance.",
        "priority": "high"
    },
    {
        "target": "Cloud-Native DevOps: Built the backend infrastructure with FastAPI (Streaming REST APIs) and established CI/CD automation frameworks for hybrid-cloud environments (Azure & On-Premises Kubernetes).",
        "replacement": "**Cloud-Native DevOps & LLM Ops:** Built **FastAPI** streaming endpoints for LLM integrations, implemented CI/CD for hybrid cloud (Azure + on-prem K8s), and added monitoring, alerting and secure deployment practices to meet reliability and data-privacy requirements.",
        "reason": "Highlight streaming LLM endpoints, monitoring, and security to align with JD's reliability/privacy and FastAPI expectations.",
        "priority": "high"
    },
    {
        "target": "Graph RAG Development: Led the design of a commercial Graph RAG system using LangChain and Microsoft GraphRAG.",
        "replacement": "**Graph RAG Development:** Led design of commercial Graph RAG using **LangChain** & Microsoft GraphRAG, adding semantic chunking, document parsing, and retrieval evaluations to improve semantic retrieval accuracy and production robustness.",
        "reason": "Make retrieval evaluation and semantic chunking explicit (matches JD's RAG and benchmarking focus) while preserving the original claim.",
        "priority": "high"
    }
]

# 加载原始简历
resume_path = Path("cv.docx")
print(f"📄 加载简历: {resume_path}")

# 解析简历
parser = ResumeParser(str(resume_path))
parsed = parser.parse()
print(f"✓ 解析完成，共 {len(parsed.all_blocks)} 个文本块\n")

# 创建修改器
modifier = ContentModifier(str(resume_path))

# 转换为ModificationInstruction对象
instructions = []
for mod in corrected_modifications:
    instructions.append(ModificationInstruction(
        target=mod['target'],
        replacement=mod['replacement'],
        reason=mod['reason'],
        priority=mod['priority']
    ))

print(f"🔧 应用 {len(instructions)} 条修改指令（已修正前导语加粗）...\n")

# 应用修改
success_count = modifier.apply_modifications(instructions)

print(f"\n✨ 完成! 成功应用 {success_count}/{len(instructions)} 条修改\n")

# 显示失败的修改
failed_logs = [log for log in modifier.logs if not log.success]
if failed_logs:
    print(f"⚠ {len(failed_logs)} 处修改未能应用:")
    for log in failed_logs:
        print(f"  - 目标: '{log.target[:60]}...'")
        print(f"    错误: {log.error_message}\n")
else:
    print("✅ 所有修改都成功应用!")

# 保存测试结果
output_path = Path("output/test_with_bold_result.docx")
output_path.parent.mkdir(parents=True, exist_ok=True)
modifier.save(str(output_path))
print(f"\n💾 已保存到: {output_path}")
