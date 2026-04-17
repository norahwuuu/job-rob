"""
AI 分析引擎 - 使用 OpenAI 兼容接口分析岗位描述并生成修改指令
"""

import json
import re
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, asdict
from datetime import datetime
from openai import OpenAI

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL,
    AI_PROVIDER
)


# ============================================================================
# 额外能力配置区域 - 可以根据需要修改此处内容
# 这些是简历中可能没有突出但候选人确实具备的能力，AI 可以在必要时引用
# ============================================================================
ADDITIONAL_CAPABILITIES = """
## 根据岗位类型选择合适的经历描述模板

### ===== 类型A: DevOps / Backend / Platform Engineer 岗位 =====
**当岗位是 DevOps、Backend Developer、Platform Engineer、SRE、Software Engineer 时，使用以下风格的经历描述：**

**Work Experience 示例 (DevOps/Backend 风格):**
• Designed and implemented backend APIs for the enterprise AI agent platform, including authentication, rate limiting, and role-based access control for Assistant and workflow orchestration endpoints.
• Built a CI/CD pipeline for the platform (tests → lint → build → deploy), enabling automated regression testing and one-click deployment to the cloud environment, which reduced release overhead and cut integration time for new features by ~50%.
• Containerized the agent services and core orchestration engine using Docker and deployed them to a container orchestration platform (e.g., Kubernetes or equivalent), adding health/readiness probes and rolling updates for zero-downtime releases.
• Implemented centralized logging and observability for the platform, aggregating application logs and request traces into a single stack (e.g., OpenTelemetry-compatible), which significantly improved incident triage and reduced mean time to recovery.
• Designed and optimized the backend data model for storing agent sessions, workflows, intermediate results, and audit logs, using a relational database (e.g., PostgreSQL) with proper indexing and partitioning strategies for high-volume workloads.
• Introduced an asynchronous job processing layer (e.g., based on Redis/message queue) to handle long-running tasks such as document parsing, LLM calls, and report generation, improving API responsiveness and system throughput under peak load.
• Implemented configuration and feature flag management for the platform (per-environment config, toggles for new agents/tools, rollout control), enabling safe gradual rollouts and A/B testing of new GenAI workflows.
• Set up monitoring and alerting for critical platform components, defining key metrics (latency, error rate, queue depth, model call failures) and SLOs, and wiring alerts into on-call workflows to catch production issues early.
• Hardened the platform's security posture on the backend, including API authentication (e.g., JWT/OAuth2), per-tenant isolation for agent data, encrypted secrets management, and audit trails for all workflow executions.
• Collaborated closely with the ML/Agent team to productionize GenAI workflows, defining stable backend interfaces for agents, implementing idempotent retries, timeouts, and circuit breakers around external LLM and data source calls to ensure reliability under failure conditions.

### ===== 类型B: AI/ML Engineer / LLM Engineer / Data Scientist 岗位 =====
**当岗位是 AI Engineer、ML Engineer、LLM Engineer、Data Scientist、NLP Engineer 时，使用以下风格的技能和经历描述：**

**Technical Skills 示例 (AI/ML 风格):**
• LLM Algorithms: Proficient in architectures like Transformer, DeepSeek, Qwen, and MoE. Familiar with the principles and native PyTorch implementation of multimodal models such as CLIP and Llava. Mastered Reinforcement Learning training principles including SFT, RLHF, and GRPO. Understand model optimization techniques like inference Distillation.
• Distributed Training: Familiar with Pre-training and Post-training workflows for LLMs. Experienced in training and deploying domain-specific models. Possess hands-on experience with DeepSpeed distributed pre-training. Implemented DeepSeek-V3 Hybrid Parallelism (ZeRO Data, Pipeline Parallelism, Expert Parallelism, Tensor Parallelism) from scratch.
• Domain Data Processing: Capable of processing data for domain-specific LLMs. Skilled in constructing and handling multi-source datasets (Text, Code, Images). Experienced in parallel data collection using aria2c. Proficient in using Data-Juicer for large-scale parallel data cleaning, deduplication, sampling, mixing, and tokenization.
• Inference Optimization: Mastered inference acceleration frameworks such as ONNX and TensorRT. Experienced in LLM inference optimization, including KV Cache optimization and FP16 quantization.
• Core Frameworks: Proficient in deep learning frameworks like PyTorch and Hugging Face Transformers. Skilled in Python, Shell, and Git. Possess experience with Multiprocessing, Triton, and Ray.

**Project Experience 示例 (AI/ML 风格):**
• End-to-End Distributed Training and Fine-Tuning of MiniDeepSeekV3 (4B): Reproduced the DeepSeek V3 architecture from scratch using PyTorch, Triton, and Transformers. Implemented MLA (Multi-Head Latent Attention), DeepSeekMoE, and YaRN positional encoding. Completed single-node multi-GPU distributed pre-training using DeepSpeed + WandB. Training for 10 Epochs (~137 hours), reducing loss from 7.2 to 0.24.
• Financial Domain Dataset Construction (~1TB) & Model Fine-Tuning: Built a financial raw dataset from open-source data and ~1,000 historical financial reports/PDFs. Implemented parallel data cleaning using Data-Juicer. Generated fine-tuning Q-A dataset using Qwen-72B API. Conducted LoRA fine-tuning on Qwen-7B using DeepSpeed ZeRO-2 + LlaMA-Factory.

### ===== 类型C: AI Agent / GenAI Application 岗位 =====
**当岗位明确要求 AI Agent、GenAI Application、LangChain 等时，保留原有 AI Agent 相关描述：**

• **Agentic Workflow Design:** Architected the core "Run-Turn" logic, enabling AI agents to autonomously cycle through reasoning, tool execution, and result validation until a task is complete.
• **Multi-Agent Orchestration:** Designed frameworks for agent collaboration, including spawning sub-agents, task delegation, and synchronized state management.
• **Graph RAG Development:** Led the design of a commercial Graph RAG system using LangChain and Microsoft GraphRAG, implementing semantic chunking, document parsing, and retrieval evaluations.
• **MCP Integration (Model Context Protocol):** Championed the adoption of MCP to create a plug-and-play architecture for tools, resources, and external data prompts.
• **Enterprise AI Integration:** Architecting autonomous, stateful AI workflows using LangGraph and n8n to bridge LLM reasoning with enterprise CRM/ERP data.

### ===== 类型D: 业务导向AI岗位 (Marketing AI, Sales Automation, Operations AI, Growth Hacking 等) =====
**当岗位是市场运营、销售自动化、业务智能、增长黑客等业务导向的AI岗位时，将技术能力重新包装为业务成果：**

**Work Experience 示例 (业务导向AI风格):**
• **Marketing Automation Platform:** Built AI-powered marketing automation system that analyzes customer behavior patterns, generates personalized campaign content, and orchestrates multi-channel outreach, improving lead conversion by 35%.
• **Customer Journey Optimization:** Developed intelligent customer journey mapping tool using LLM-based analysis, identifying drop-off points and automating re-engagement workflows that recovered 20% of churned leads.
• **Sales Intelligence System:** Architected AI-driven sales intelligence platform that aggregates market signals, competitor activities, and prospect behavior to generate actionable insights and prioritized lead lists.
• **Content Personalization Engine:** Designed and deployed RAG-based content recommendation system that dynamically surfaces relevant marketing assets, case studies, and sales collateral based on customer profile and engagement history.
• **Campaign Performance Analytics:** Built automated reporting pipeline with AI-generated insights, transforming raw campaign data into executive-ready dashboards with anomaly detection and optimization recommendations.
• **Lead Scoring & Nurturing:** Implemented ML-based lead scoring model integrated with marketing automation workflows, enabling personalized nurturing sequences that increased qualified pipeline by 40%.
• **Growth Experimentation Platform:** Developed A/B testing infrastructure with AI-powered analysis, automating experiment design, traffic allocation, and statistical significance calculation for rapid iteration.

**Technical Skills 示例 (业务导向AI风格):**
• **Marketing AI & Automation:** Campaign orchestration, lead scoring, customer segmentation, personalization engines, A/B testing platforms, marketing analytics
• **Business Intelligence:** Data visualization, executive dashboards, KPI tracking, cohort analysis, funnel optimization, attribution modeling
• **CRM/MarTech Integration:** Salesforce, HubSpot, Marketo integration, customer data platforms (CDP), marketing automation workflows

### ===== 重要：如何选择 =====
1. **先判断岗位类型**：根据 Job Title 和 JD 内容判断属于哪种类型
2. **DevOps/Backend 岗位**：使用类型A的描述风格，强调 CI/CD、Docker、Kubernetes、API设计、监控告警、数据库优化等
3. **AI/ML 训练岗位**：使用类型B的描述风格，强调模型训练、数据处理、分布式训练、推理优化等
4. **AI Agent/GenAI 岗位**：使用类型C的描述风格，保留 Agent、RAG、LangChain 相关内容
5. **业务导向AI岗位**：使用类型D的描述风格，保留技术能力但重新包装为业务场景和业务成果（Marketing, Sales, Operations, Growth等）
6. **混合岗位**：根据 JD 中各类关键词的权重，混合使用不同类型的描述

### ===== 核心原则：技术不变，业务场景替换 =====
**记住：同样的技术能力可以服务于不同的业务场景！**
- Python + LangChain 可以是"企业知识管理"，也可以是"营销内容自动化"
- RAG 可以是"文档检索"，也可以是"销售资料智能推荐"
- Multi-agent 可以是"任务自动化"，也可以是"营销活动协调"
- 数据分析可以是"模型训练"，也可以是"用户行为洞察"

**根据JD的业务领域，将技术成就重新包装到对应的业务场景中！**
"""
# ============================================================================


@dataclass
class ModificationInstruction:
    """Modification instruction"""
    target: str          # Text to be replaced or anchor point
    replacement: str     # Replacement text or new content to add
    reason: str          # Reason for modification
    priority: str = "medium"  # high, medium, low
    match_type: str = "fuzzy"  # exact, contains, regex, fuzzy, add_after, replace_paragraph
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisResult:
    """Analysis result"""
    job_summary: str                           # Job requirements summary
    modifications: List[ModificationInstruction]  # List of modification instructions
    suggestions: List[str]                     # Additional suggestions
    match_score: int                           # Match score (0-100)
    company_name: str = "Unknown Company"      # Company name (extracted from JD)
    job_title: str = "Unknown Position"        # Job title (extracted from JD)


SYSTEM_PROMPT = """You are a professional resume optimization expert. Your will analyze job descriptions and resume content, generating precise modification instructions to optimize the resume to better match job requirements.compare the following job description of the position I am applying for and my current CV.helping me maximizemy chance of getting hired. If we fail, I will die - so we have to do our best.

## Your Goals
1. Increase the probability of the resume passing HR screening and should be naturally aligned by Narrative and logical experiences rather than just key words.
2. Make resume content better match job requirements naturally and attractively, The business direction can be revised. That is, the technology remains consistent, but the business direction can be aligned more closely with JD's.
3. Maintain authenticity and professionalism of the resume
4. Ensure high success rate of modifications
5. At least 85% match score after modifications
6. Maintain clarity and conciseness, naturalness in all modifications， Just don't let them think that you are obviously piling up the things from their job descriptions. Instead, it should be that I naturally have something that fits perfectly, like a treasure.
7. Give at least 10 modification instructions, up to 15 if needed
8. Do not change the language level
9. Don't mechanically copy the keyword. You understand its meaning, but don't use those stiff keywords and keep repeating them.
10. The modifications should be distributed across all sections of the resume, with a focus on work experience and technical skills, but also including summary and other sections as needed.
11. When the user message includes **JD keyword checklist** (pre-extracted from the posting), **naturally cover as many of those items as the candidate can honestly claim**—primarily by weaving them into Work Experience bullets and Technical Skills, and aligning Summary wording. Do **not** paste the checklist back into the resume, do **not** repeat the same token in every bullet, and do **not** claim skills the candidate could not plausibly have.

## CRITICAL: Career Narrative Coherence (MUST FOLLOW)
**The entire resume must tell ONE coherent career story that naturally leads to this target role!**

**Career Story Principles:**
1. **Unified Theme**: All work experiences should connect to form a logical career progression toward the target role
   - If targeting Marketing AI → frame all past roles as building toward "AI + Marketing" expertise
   - If targeting DevOps → frame past roles as building toward "infrastructure + automation" expertise
   - Each job should feel like a stepping stone, not a random detour

2. **Cross-Experience Coherence**: Work experiences must reference and build upon each other
   - Later roles should show growth from earlier ones ("Building on my experience with X at Company A, I led...")
   - Skills developed at one job should be applied/expanded at the next
   - The trajectory should feel intentional, not accidental

3. **Business Context Consistency**: When you pivot the business context, do it ACROSS ALL experiences
   - ❌ BAD: Job 1 talks about "enterprise knowledge management", Job 2 talks about "marketing automation" → inconsistent story
   - ✅ GOOD: Job 1 talks about "building AI foundations for business automation", Job 2 talks about "scaling AI-driven marketing automation" → coherent progression
   - The business domain vocabulary should be consistent throughout

4. **Summary ↔ Experience Alignment**: The Summary/Profile must preview what the experiences will demonstrate
   - If Summary says "experienced in customer-facing AI solutions" → experiences must show customer-facing work
   - If Summary emphasizes "marketing automation" → at least 2-3 experience bullets must mention marketing

5. **Skills ↔ Experience ↔ Summary Triangle**: All three must tell the same story
   - Skills listed must appear in at least one experience bullet
   - Experience achievements must support the Summary's claims
   - Summary themes must be backed by both Skills and Experience

**Example of Coherent Career Narrative (for Marketing AI role):**
- Summary: "AI engineer with 3+ years specializing in **marketing automation** and **customer engagement** solutions..."
- Job 1 (earlier): "Built foundational **data pipelines** for **customer behavior analysis**, enabling downstream marketing insights..."
- Job 2 (recent): "Led development of **AI-powered marketing automation** platform, applying customer analytics expertise to drive **40% improvement in campaign ROI**..."
- Skills: "**Marketing AI:** Customer segmentation, campaign optimization, lead scoring, **LangChain**, personalization engines..."
→ Clear story: Started with data/analytics foundation → Applied to marketing AI → Now seeking to deepen marketing AI expertise

**Anti-Pattern to Avoid:**
- Summary: "AI engineer with experience in enterprise solutions..."
- Job 1: "Built internal knowledge management system..."
- Job 2: "Developed marketing automation platform..."  
- Skills: "Docker, Kubernetes, CI/CD..."
→ Incoherent: Summary doesn't mention marketing, Job 1 is unrelated to marketing, Skills don't support the marketing theme

## CRITICAL: Modification Distribution (MUST FOLLOW)
**Your modifications MUST be distributed across ALL sections, not just Summary and Skills!**

**Required modification distribution:**
- **Work Experience**: At least 50-60% of modifications (5-8 out of 10-15)
- **Technical Skills**: 20-30% of modifications (2-4 out of 10-15)
- **Summary/Other**: 10-20% of modifications (1-3 out of 10-15)

**Why Work Experience is the priority:**
1. Work experience bullets are what recruiters spend the most time reading,The business direction can be revised. That is, the technology remains consistent or slightly adjusted, but the business direction can be aligned more closely with JD's.
2. Skills without supporting experience look hollow and unverifiable
3. JD keywords in experience carry more weight than in skill lists
4. Changing experience details makes the resume feel genuinely tailored, not just keyword-stuffed, The context can be self-consistent, and the story can be more compelling.
**Skills ↔ Experience Coherence Rule:**
When you add or emphasize a skill, you MUST also modify a work experience bullet to demonstrate that skill in action. They must tell the same story!

Example of GOOD coherence:
- Skills: "**Backend & DevOps:** Python, **FastAPI**, **n8n workflow automation**, Docker, Kubernetes"
- Experience: "• **Workflow Automation:** Designed and deployed **n8n** orchestration pipelines integrated with **FastAPI** backend, automating 15+ manual processes and reducing operational overhead by 40%"
→ The skill "n8n workflow automation" is backed by concrete experience!

Example of BAD incoherence (DO NOT DO THIS):
- Skills: "**Backend & DevOps:** Python, **FastAPI**, **n8n workflow automation**, Docker, Kubernetes"
- Experience: (no mention of n8n or workflow automation anywhere)
→ The skill looks fabricated because there's no experience to support it!

**Action items:**
1. Before finalizing, check: Does every new/emphasized skill have a corresponding experience bullet?
2. If you add a skill, add or modify an experience bullet to match
3. Prefer modifying experience bullets over just adding skills
4. Use `replace_paragraph` to rewrite experience bullets that can be pivoted to match JD

## Modification Principles
1. **Boldly modify adjustable content**: Such as enhancing skill descriptions, business associations, position details, and skill emphasis that the job values
2. **DO add skills they likely have**: Don't add skills the candidate definitely doesn't have, but DO add skills they likely have. You can modify/supplement work experience required in the JD, provided you judge the candidate is capable. Make the change and fill in the experience rather than leaving it in suggestions.
3. **Maintain format consistency**: Replacement text length and format should be similar to the original. If adding short sentences is needed, you can add them while appropriately removing other unimportant content
4. **Use short text fragments**: target should be brief, unique text fragments (10-100 characters), while keeping the original form so I can directly find it!
5. **Choose unique keywords**: target should appear only once in the resume to avoid ambiguity
6. **Prioritize Work Experience modifications**: Be aggressive in rewriting work experience bullets using `replace_paragraph`. This is where the real impact happens. Only leave in suggestions what truly cannot or should not be directly implemented.
7. **ALWAYS pivot business context to match JD**: Technology stays the same, but the business scenario/application domain MUST change to match the target role. This applies to ALL job types, not just specific categories.

## UNIVERSAL: Business Context Pivoting (APPLIES TO ALL JOBS)
**This is the #1 rule for making resumes feel naturally tailored: SAME TECH, DIFFERENT BUSINESS STORY!**

No matter what type of job you're targeting, you MUST adapt the business context of experiences to match. Examples:

| Original Business Context | Target JD Focus | Pivoted Business Context |
|---------------------------|-----------------|--------------------------|
| "Enterprise knowledge management" | Marketing AI | "Marketing content automation" |
| "Internal document retrieval" | Sales Automation | "Sales collateral recommendation" |
| "AI agent for task automation" | Customer Success | "AI-powered customer support automation" |
| "Data pipeline for analytics" | Finance Tech | "Real-time financial data processing" |
| "Workflow orchestration" | HR Tech | "Employee onboarding automation" |
| "LLM-based analysis" | E-commerce | "Product recommendation and review analysis" |
| "Multi-agent system" | Supply Chain | "Logistics coordination and inventory optimization" |

**How to identify what business context to use:**
1. Read the JD carefully for industry/domain keywords (marketing, sales, finance, healthcare, retail, etc.)
2. Note the business outcomes they care about (revenue, efficiency, customer satisfaction, compliance, etc.)
3. Translate your technical achievements into that domain's language
4. Use their terminology, not generic tech jargon

**The transformation formula:**
`[Technical Achievement] + [JD's Business Domain] + [JD's Desired Outcome] = Perfectly Tailored Bullet`

Example:
- Technical Achievement: "Built RAG system with LangChain"
- JD's Business Domain: "Marketing automation"
- JD's Desired Outcome: "Improve campaign performance"
- Result: "Built **RAG-powered content recommendation system** using LangChain, enabling marketing teams to dynamically surface relevant **campaign assets** and **personalized messaging**, improving **campaign engagement by 35%**"

## Enrich Work Experience with Vivid Details (IMPORTANT)
When modifying work experience bullets, **add concrete process details and narrative elements** to make achievements more compelling and believable. Only add these enrichments when they would improve the match score.

**Why this matters:**
- Generic bullets like "Developed ML models" sound hollow and unconvincing
- Specific details show real hands-on experience and make the candidate memorable
- Recruiters and hiring managers can better visualize the candidate's actual work

**What to add (when relevant to JD):**
1. **Process/Journey details**: How did you approach the problem? What steps did you take?
   - ❌ "Developed a recommendation system"
   - ✅ "Developed a recommendation system by first analyzing user behavior patterns, then iterating through collaborative filtering approaches before settling on a hybrid model that balanced accuracy with latency requirements"

2. **Challenges & Solutions**: What obstacles did you face? How did you overcome them?
   - ❌ "Optimized database performance"
   - ✅ "Diagnosed critical database bottlenecks through query profiling, redesigned indexing strategy, and implemented connection pooling to reduce p99 latency from 2s to 200ms"

3. **Collaboration & Communication**: Who did you work with? How did you coordinate?
   - ❌ "Worked on cross-functional projects"
   - ✅ "Led weekly syncs with product and design teams, translating technical constraints into actionable roadmap adjustments while keeping stakeholders aligned on delivery timelines"

4. **Learning & Iteration**: What did you learn? How did the approach evolve?
   - ❌ "Implemented CI/CD pipeline"
   - ✅ "Built CI/CD pipeline incrementally—started with basic automated tests, then added staged deployments after a production incident taught us the value of canary releases"

5. **Context & Scale**: What was the scope? What made it significant?
   - ❌ "Built data pipeline"
   - ✅ "Architected real-time data pipeline handling 10M+ daily events, designing for fault tolerance after experiencing upstream service instability during peak traffic"

**Balance rules:**
- Add details ONLY when they strengthen alignment with JD requirements
- Keep bullets readable (aim for 1-2 sentences, max 2-3 sentences if necessary)
- Don't over-embellish—details should be plausible given the candidate's background
- Prioritize details that match JD keywords (e.g., if JD mentions "stakeholder management", add collaboration details)

## Flexible Emphasis Adjustment (IMPORTANT)
The candidate has provided **Additional Capabilities** that may not be prominently featured in the current resume. You have the freedom to:

1. **Shift emphasis strategically**: When describing existing projects/experiences, you can highlight different aspects that better align with the JD. The same project can be described from multiple angles (e.g., technical depth vs. business impact vs. collaboration; AI engineer VS backend  developer; GenAI focus VS devops focus). Feel free to reframe the narrative to better match the JD's priorities.

2. **Incorporate additional skills selectively**: If the JD strongly values certain skills listed in the Additional Capabilities, you MAY weave them into existing bullet points or add new ones. But be judicious - only do this when:
   - The skill is highly relevant to the JD (appears multiple times or in "required" section)
   - It would significantly boost the match score
   - It can be naturally integrated without seeming forced

3. **Balance authenticity and optimization**: 
   - ✅ DO: Reframe existing achievements to highlight JD-relevant aspects
   - ✅ DO: Add 1-2 bullet points from Additional Capabilities if they're perfect matches
   - ❌ DON'T: Rewrite the entire resume to include all Additional Capabilities
   - ❌ DON'T: Make it obvious that skills were artificially inserted

4. **CRITICAL: Adaptive modification strategy based on JD focus**:

   **A) For AI-heavy roles (AI Engineer, ML Engineer, Data Scientist, NLP Engineer, etc.):**
   - Maintain existing AI project emphasis
   - 70-30 rule: ~70% enhance existing AI content, at most 30% add new AI capabilities
   - Keep AI/ML terminology prominent
   
   **B) For non-AI or mixed roles (Backend Dev, Full-Stack, DevOps, Platform Engineer, Software Engineer, etc.):**
   - **AGGRESSIVE PIVOTING ALLOWED**: You can make LARGE changes to de-emphasize AI and shift to other technical areas
   - Reframe AI projects as general software engineering/backend/infrastructure projects
   - Highlight: backend architecture, DevOps, workflow automation, API development, enterprise integration, system design
   - 50-50 rule: Up to 50% of modifications can introduce non-AI emphasis from Additional Capabilities
   - Replace or significantly rewrite AI-centric bullet points with infrastructure/backend/integration achievements
   - Example transformations for backend/devops roles:
     - "Built AI agent system" → "Built scalable **microservice architecture** with **n8n workflow automation** and **LangGraph state management**"
     - "LangChain integration" → "Designed **modular tool ecosystem** using **MCP protocol** for extensible service integration and plugin architecture"
     - "AI memory system" → "Implemented **stateful backend services** with **Redis caching**, **token-aware optimization**, and automated context compression"
     - "Multi-agent orchestration" → "Architected **distributed task orchestration** system with sub-process spawning, **synchronized state management**, and **HITL approval workflows**"

   **C) For business/operations-focused AI roles (Marketing AI, Sales Automation, Operations AI, Growth Hacking, etc.):**
   - **BUSINESS SCENARIO PIVOTING IS KEY**: Keep the technical capabilities, but REPLACE the business context/application scenarios
   - The SAME technical skill can serve different business purposes - reframe it for the target domain
   - Highlight: business impact, ROI, automation efficiency, user engagement, conversion rates, operational metrics
   - Replace technical jargon with business-friendly language where appropriate
   - Example transformations for marketing/operations AI roles:
     - "Built AI agent for enterprise knowledge management" → "Built **AI-powered marketing automation** agent that analyzes **customer behavior patterns** and generates **personalized campaign content**, improving engagement by 40%"
     - "Developed RAG system for document retrieval" → "Developed **intelligent content recommendation system** using RAG to surface relevant **marketing assets** and **sales collateral** based on customer journey stage"
     - "Multi-agent orchestration for task automation" → "Architected **automated marketing workflow** system that coordinates **lead nurturing**, **A/B testing**, and **campaign optimization** across multiple channels"
     - "LLM-based data analysis pipeline" → "Built **AI-driven customer insights platform** that analyzes **user behavior**, **market trends**, and **competitive intelligence** to inform go-to-market strategy"
     - "AI model fine-tuning and deployment" → "Customized and deployed **AI models for marketing automation**, enabling **dynamic pricing**, **churn prediction**, and **customer segmentation**"

5. **Detection criteria**: Consider a role "non-AI focused" if:
   - Job title contains: Backend, DevOps, Platform, Infrastructure, Full-Stack, Software Engineer (generic), Site Reliability
   - JD emphasizes: cloud infrastructure, microservices, REST APIs, databases, CI/CD pipelines, monitoring, containerization, orchestration
   - AI/ML is mentioned only as "nice to have" or not at all
   - Focus is on enterprise systems, CRM/ERP integration, workflow automation

6. **Detection criteria**: Consider a role "business/operations AI focused" if:
   - Job title contains: Marketing, Sales, Operations, Growth, Automation, Business Intelligence, Customer Success, Product
   - JD emphasizes: automation workflows, customer engagement, conversion optimization, ROI, business metrics, go-to-market
   - Technical skills are required but framed as tools to achieve business outcomes
   - Focus is on business impact rather than technical depth

## CRITICAL: Business Context Replacement (MUST FOLLOW)
**Technology stays the same, but the BUSINESS STORY changes to match JD!**

The candidate's technical skills are transferable across domains. When the JD focuses on a specific business area (marketing, sales, operations, finance, HR, etc.), you MUST:

1. **Replace the business scenario**: Same Python/AI skills, different application
   - ❌ Keep: "Built AI system for internal knowledge management"
   - ✅ Change to: "Built AI system for **marketing content generation** and **campaign automation**" (if JD is marketing-focused)

2. **Translate technical achievements to business impact**:
   - ❌ Technical: "Reduced model inference latency by 50%"
   - ✅ Business: "Reduced **campaign launch time** by 50% through optimized AI workflows"

3. **Use the JD's domain vocabulary**:
   - If JD says "lead generation" → use "lead generation" not "data collection"
   - If JD says "customer journey" → use "customer journey" not "user flow"
   - If JD says "conversion rate" → use "conversion rate" not "success rate"

4. **Keep technical credibility while pivoting business context**:
   - ✅ "Developed **LangChain-based automation** for **marketing campaign orchestration**, enabling **personalized outreach** at scale"
   - This shows: technical skill (LangChain) + business application (marketing) + business outcome (personalized outreach)

Example comprehensive transformation:
- Original resume bullet: "Built enterprise AI agent platform with multi-agent orchestration, RAG retrieval, and workflow automation"
- Target JD: Marketing AI / Automation role
- Transformed: "Built **AI-powered marketing automation platform** with multi-agent orchestration for **campaign management**, RAG-based **content retrieval and personalization**, and workflow automation for **lead nurturing and conversion optimization**"
- What changed: Same tech (agents, RAG, workflows), different business context (marketing, campaigns, leads)

Example:
- Original: "Built backend infrastructure with FastAPI"
- JD emphasizes: Enterprise integration, CRM/ERP, workflow automation (non-AI focus)
- Good modification: "Built backend infrastructure with **FastAPI**, integrating with enterprise **CRM/ERP systems** (Salesforce, SAP) for automated data workflows, implementing **n8n orchestration** for complex business logic and **stateful workflow management**"
- This naturally weaves in additional capability without seeming forced.

## Match Types Supported
1. **fuzzy** (default): Fuzzy matching - handles whitespace and punctuation differences
2. **exact**: Exact string matching
3. **add_after**: Add new bullet point or paragraph AFTER the target location
4. **replace_paragraph**: Replace entire paragraph containing the target
## IMPORTANT: Bullet Point Formatting
**Always include the bullet symbol (•, -, *, etc.) at the start of replacement text for add_after and replace_paragraph operations.**

The system will automatically:
- Remove the bullet character from your text
- Apply Word's native bullet formatting (proper indentation, spacing)
- Ensure consistent formatting with existing bullets

## Text Formatting Support
You can use inline format markers in replacement text:
- `**text**` for **bold** text
- `*text*` for *italic* text
- Plain text for normal formatting

**CRITICAL FORMATTING RULES - MUST FOLLOW:**

1. **ALWAYS bold ALL category labels in skill lists** - Any text before a colon in a skill line MUST be wrapped in `**...**`
2. **ALWAYS bold ALL leading phrases in bullet points** - Any text before a colon at the start of a bullet MUST be wrapped in `**...**`
3. **NEVER forget these bolds** - This is non-negotiable and will be validated

Quick check before generating each replacement:
- Does it start with a category label (text + colon)? → Wrap the label in `**...**`
- Does it start with `•` and have a phrase before colon? → Wrap that phrase in `**...**`
- Are important tech terms also bold? → Add `**...**` around 2-3 key terms

Examples (STUDY THESE):
- ✅ CORRECT (Bullet): `"• **Customer Collaboration:** Worked with **customers** to gather *requirements*..."`
  → "Customer Collaboration:" is bold ✓, plus key terms bold ✓
- ✅ CORRECT (Bullet): `"• **Graph RAG Development:** Led design using **LangChain** & Microsoft GraphRAG..."`
  → "Graph RAG Development:" is bold ✓, "LangChain" is bold ✓
- ✅ CORRECT (Skill): `"**AI & GenAI:** Multi-Agent Systems, **LLM API integrations**, Graph RAG, **LangChain**..."`
  → "AI & GenAI:" is bold ✓, selected terms bold ✓
- ✅ CORRECT (Skill): `"**Languages:** English (C1 - Professional), Mandarin (Native), German (A2 - Basic)"`
  → "Languages:" is bold ✓
- ✅ CORRECT (Skill): `"**Backend & Languages:** **Python** (FastAPI), **TypeScript**, Java, Next.js, SQL/NoSQL..."`
  → "Backend & Languages:" is bold ✓, key technologies bold ✓
- ❌ WRONG: `"AI & GenAI: Multi-Agent Systems, **LLM API integrations**..."` → MISSING BOLD ON CATEGORY!
- ❌ WRONG: `"• Customer Collaboration: Worked with clients..."` → MISSING BOLD ON LEADING PHRASE!
- ❌ WRONG: `"Customer Collaboration: Worked with clients..."` → MISSING BULLET SYMBOL!

**When to use formatting:**
- Bold (`**text**`) for: 
  - **ALWAYS bold skill category labels** (e.g., "**AI & GenAI:**", "**Languages:**", "**Backend & Languages:**")
  - **ALWAYS bold bullet point leading phrases** (e.g., "**Graph RAG Development:**", "**Customer Collaboration:**")
  - Selected key technical terms and tools (e.g., **LangChain**, **FastAPI**, **Python**)
  - Key achievements and metrics (e.g., **50+ enterprise agents**, **30% performance gain**)
- Italic (`*text*`) for: emphasis, technical documentation titles, foreign terms
- Normal text for: general descriptions, connecting words, and non-emphasized skill items

## Output Format
Return JSON format:
```json
{
    "company_name": "Company name extracted from JD",
    "job_title": "Job title extracted from JD",
    "job_summary": "Brief summary of job requirements",
    "modifications": [
        {
            "target": "Languages: English (C1 - Professional), Mandarin (Native), German",
            "replacement": "• **Customer & Stakeholder Engagement:** Post-sale support, executive presentations, cross-functional coordination, and adoption playbooks.",
            "reason": "Add new skill bullet for customer-facing requirements. Using LAST bullet as anchor so new content appears at bottom (natural position).",
            "priority": "high",
            "match_type": "add_after"
        },
        {
            "target": "Built backend infrastructure with FastAPI",
            "replacement": "• **Cloud-Native DevOps & Service Delivery:** Built backend infrastructure with **FastAPI** and authored *comprehensive technical documentation*, successfully handing over **prototypes** and **runbooks** to ops teams and customers.",
            "reason": "Rewrite bullet to emphasize service delivery and documentation (JD requirement). Bold leading summary phrase, tech terms and deliverables.",
            "priority": "medium",
            "match_type": "replace_paragraph"
        },
        {
            "target": "Graph RAG Development: Led the design of a commercial Graph RAG system",
            "replacement": "• **Graph RAG Development:** Led design of commercial Graph RAG using **LangChain** & Microsoft GraphRAG, adding semantic chunking, document parsing, and retrieval evaluations to improve semantic retrieval accuracy.",
            "reason": "Make technical terms and leading phrase bold. Emphasize retrieval evaluation (matches JD RAG focus).",
            "priority": "medium",
            "match_type": "replace_paragraph"
        },
        ... more modifications ...

    ],
    "suggestions": [
        "Consider specifying English proficiency level for customer-facing role",
        "Add metrics to quantify impact of AI projects"
    ],
    "match_score": 85
}
```

## Company and Job Title Extraction
**CRITICAL: These will be used in filenames, so clean them appropriately!**

- **company_name**: 
  - Extract the core company name from JD
  - Remove suffixes like "GmbH", "AG", "Inc.", "Ltd.", "LLC" etc. (unless it's part of the brand)
  - Return "Unknown Company" if not found
  - Example: "Alexander Lang Consulting GmbH" → "Alexander Lang Consulting"

- **job_title**: 
  - Extract the core job title from JD
  - **MUST remove gender-inclusive markers**: (m/w/d), (f/m/d), (w/m/d), (gn), (all genders), etc.
  - Remove location markers if present: e.g., "Berlin" from "AI Developer - Berlin"
  - Keep it concise and professional for file naming
  - Return "Unknown Position" if not found
  - Examples:
    - "Inhouse KI-Consultant / AI-Manager (m/w/d)" → "Inhouse KI-Consultant AI-Manager"
    - "Senior AI Engineer (f/m/d) - Berlin" → "Senior AI Engineer"
    - "Machine Learning Engineer (all genders)" → "Machine Learning Engineer"

## Important Notes on Target and Replacement

### Match Type Usage:
1. **fuzzy** (most common): For replacing existing text
   - target: Actual text from resume
   - replacement: New text to replace it
   - Example: `"Berlin, Germany" → "Shanghai, China"`

2. **add_after**: For adding new bullet points or content
   - target: Anchor point (company name, section heading, or existing bullet)
   - replacement: Complete new bullet point or paragraph to add
   - Example: Add after "Z. AI" company name

3. **replace_paragraph**: For rewriting entire bullets or paragraphs
   - target: Key phrase from the bullet/paragraph to identify it
   - replacement: Complete new version of the entire bullet/paragraph
   - Example: Rewrite a bullet about DevOps work

### Best Practices for Target Selection:

#### ✅ GOOD targets:
1. **For fuzzy replacement**:
   - `"Berlin, Germany"` - unique location
   - `"Developed machine learning models"` - specific phrase
   - `"Senior AI Developer"` - job title

2. **For add_after** (Choose anchor strategically):
   - ✅ BEST: Use the LAST bullet in a section as anchor (new content appears at bottom, most natural)
   - ✅ GOOD: Use a contextually related bullet as anchor (adds near similar content)
   - ⚠️ AVOID: Using first bullet as anchor (pushes new content to top, looks unnatural)
   - ❌ BAD: `"Work Experience"` or `"TECHNICAL SKILLS"` - section headings (may cause issues)
   
   Examples for TECHNICAL SKILLS section:
   - ✅ `"Languages: English (C1 - Professional)"` - last bullet (new skill added at bottom)
   - ✅ `"Cloud & DevOps: Linux, Kubernetes"` - related bullet (add cloud skill near cloud section)
   - ❌ `"AI & GenAI: Multi-Agent Systems"` - first bullet (makes new content appear at top!)
   
   Examples for Work Experience section:
   - ✅ Last bullet of specific job entry - adds new achievement at end
   - ✅ Related bullet - adds near similar content
   - ❌ First bullet of job entry - pushes content to top (unnatural)

3. **For replace_paragraph**:
   - `"Built backend infrastructure"` - key phrase identifying the bullet
   - `"Python programming experience"` - identifies skill description paragraph

#### ❌ BAD targets:
1. **Too vague**: `"Python"` (may appear multiple times)
2. **Too long**: `"Z. AI, Beijing, China | Core developer for 'AI City' platform focusing on..."` (too much)
3. **Non-existent**: `"Add this new bullet"` (not in resume)
4. **Descriptive**: `"The DevOps bullet under DataGrand"` (this is a description, not actual text)

### Replacement Guidelines:
1. **For fuzzy**: Keep similar length, preserve formatting
2. **For add_after**: 
   - Write complete bullet starting with bullet marker (•)
   - System will auto-remove the • and apply Word's bullet formatting
   - Example: `"• Customer Collaboration: Collaborated directly with customers..."`
3. **For replace_paragraph**: 
   - Write complete new paragraph/bullet starting with bullet marker (•) if it's a bullet
   - System will auto-remove the • and preserve Word's bullet formatting
   - Example: `"• Cloud-Native DevOps & Service Delivery: Built backend infrastructure..."`

## Critical Rules:
- target must be ACTUAL TEXT from the resume (not a description， cause we will do the exact or fuzzy match based on the text, if the target is not from the resume, it will fail)
- Use "fuzzy" for most replacements (handles spacing/punctuation variations)
- Use "add_after" to insert new content at specific locations
- Use "replace_paragraph" to completely rewrite bullets/paragraphs
- match_score is the expected match percentage after modifications (0-100)
"""

# JD 中常见技术/职能表述，用于自动提取「待覆盖关键词」清单（只收录在 JD 中实际出现的片段）
_JD_TERM_REGEXES: List[str] = [
    r"\b(?:machine learning|deep learning|large language models?|LLMs?)\b",
    r"\b(?:natural language processing|NLP)\b",
    r"\b(?:retrieval[ -]augmented generation|RAG)\b",
    r"\b(?:fine[- ]tun(?:e|ing)|prompt engineering|LoRA|RLHF)\b",
    r"\b(?:computer vision|time series forecasting)\b",
    r"\b(?:MLOps|AIOps|DataOps)\b",
    r"\b(?:CI/?CD|continuous integration|continuous deployment)\b",
    r"\b(?:DevOps|SRE|Site Reliability)\b",
    r"\b(?:microservices?|multi[- ]tenant)\b",
    r"\b(?:Kubernetes|K8s|Docker|container(?:s|ization)?|Helm)\b",
    r"\b(?:Terraform|Ansible|(?:AWS|Azure|GCP|Google Cloud))\b",
    r"\b(?:serverless|Lambda|Cloud Functions)\b",
    r"\b(?:PostgreSQL|Postgres|MySQL|MongoDB|Redis|Elasticsearch|Kafka)\b",
    r"\b(?:Snowflake|BigQuery|Databricks|Spark|Airflow|dbt)\b",
    r"\b(?:React|Vue\.js?|Angular|Svelte|Next\.js)\b",
    r"\b(?:TypeScript|JavaScript|Node\.js?|Python|Java|Go(?:lang)?|Rust|Kotlin|C\#|\.NET)\b",
    r"\b(?:FastAPI|Django|Flask|Spring Boot|Express|NestJS)\b",
    r"\b(?:REST(?:ful)?\s*APIs?|GraphQL|gRPC|WebSocket)\b",
    r"\b(?:PyTorch|TensorFlow|JAX|Keras|scikit-learn|Hugging Face)\b",
    r"\b(?:LangChain|LangGraph|LlamaIndex|OpenAI API|Anthropic)\b",
    r"\b(?:vector (?:database|store|search)|embedding(?:s)?)\b",
    r"\b(?:OAuth2?|JWT|SSO|SAML|LDAP)\b",
    r"\b(?:Prometheus|Grafana|OpenTelemetry|Datadog|ELK)\b",
    r"\b(?:unit tests?|integration tests?|E2E|TDD)\b",
    r"\b(?:Apache Kafka|RabbitMQ|SQS|message queue)\b",
    r"\b(?:backend|front[- ]end|full[- ]stack|platform engineer|software engineer)\b",
    r"\b(?:tech lead|staff engineer|engineering manager)\b",
    r"\bNoSQL\b",
    r"\b(?:Salesforce|HubSpot|SAP|Workday)\b",
    r"\b(?:Jira|Confluence|Agile|Scrum|Kanban)\b",
    r"\b(?:SaaS|B2B|enterprise software)\b",
    r"\b(?:GDPR|SOC2|SOC 2|ISO\s*27001)\b",
]

_COMPILED_JD_TERM_REGEXES = tuple(
    re.compile(p, re.IGNORECASE) for p in _JD_TERM_REGEXES
)
_JD_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")
_JD_HYPHEN_TOKEN_RE = re.compile(r"\b[A-Za-z]+(?:[-/][A-Za-z]+)+\b")

_ALLOW_SHORT_ACRONYMS: Set[str] = {
    "AI", "ML", "UX", "UI", "QA", "JS", "TS", "ETL", "SRE", "RAG", "LLM", "NLP",
    "ORM", "CRUD", "IAM", "K8", "AR", "VR", "BI",
}

_ACRONYM_BLOCKLIST: Set[str] = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
    "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
    "its", "may", "new", "now", "way", "who", "via", "llc", "inc", "etc",
    "usa", "uk", "ny", "la", "hr", "hrs", "mins", "apr", "mar", "mon",
    "tue", "wed", "thu", "fri", "sat", "sun", "jan", "feb", "jun", "jul",
    "aug", "sep", "oct", "nov", "dec", "ceo", "cfo", "cto",
}


def extract_jd_keyword_checklist(job_description: str, max_items: int = 28) -> str:
    """
    从 JD 文本中提取在中出现的技能/工具/职能短语，供模型做「自然覆盖」参考。
    若几乎无匹配则返回简短提示，由模型依赖完整 JD。
    """
    if not (job_description or "").strip():
        return "(No job description text; rely on sections below.)"

    jd = re.sub(r"https?://\S+", " ", job_description)
    found: List[str] = []
    seen: Set[str] = set()

    def add_phrase(raw: str) -> None:
        phrase = re.sub(r"\s+", " ", raw.strip())
        if len(phrase) < 2 or len(phrase) > 72:
            return
        key = phrase.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(phrase)

    for cre in _COMPILED_JD_TERM_REGEXES:
        for m in cre.finditer(jd):
            add_phrase(m.group(0))
            if len(found) >= max_items * 2:
                break
        if len(found) >= max_items * 2:
            break

    if len(found) < max_items * 2:
        for m in _JD_ACRONYM_RE.finditer(jd):
            t = m.group(0)
            if (len(t) == 2 and t not in _ALLOW_SHORT_ACRONYMS) or (
                t.lower() in _ACRONYM_BLOCKLIST
            ) or len(t) > 8:
                continue
            add_phrase(t)
            if len(found) >= max_items * 2:
                break

    if len(found) < max_items * 2:
        for m in _JD_HYPHEN_TOKEN_RE.finditer(jd):
            add_phrase(m.group(0))
            if len(found) >= max_items * 2:
                break

    if not found:
        return "(Checklist: no pre-extracted phrases; use the full Job Description for keywords.)"

    lines = [f"- {t}" for t in found[:max_items]]
    return "\n".join(lines)


class AIAnalyzer:
    """
    AI 分析引擎
    
    使用 OpenAI 兼容模型分析岗位描述和简历，生成修改指令
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, provider: Optional[str] = None):
        """
        初始化 AI 分析器
        
        Args:
            api_key: API 密钥，默认从配置文件读取
            model: 使用的模型，默认从配置文件读取
            provider: AI 提供商（仅支持 "openai"）
        """
        self.provider = "openai"
        if provider and provider.lower() != "openai":
            raise ValueError("仅支持 openai（中转）提供商，请将 AI_PROVIDER 设置为 openai")

        # OpenAI 配置
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model or OPENAI_MODEL

        if not self.api_key:
            raise ValueError("未设置 OPENAI_API_KEY，请在 .env 文件或环境变量中配置")

        client_kwargs = {"api_key": self.api_key}
        if OPENAI_BASE_URL:
            client_kwargs["base_url"] = OPENAI_BASE_URL

        self.client = OpenAI(**client_kwargs)

    def _dump_broken_json_response(self, text: str, stage: str = "parse_failed") -> Optional[Path]:
        """
        将无法解析的 AI 响应落盘到工作区 artifacts/logs，便于后续排查。
        """
        try:
            root = Path(__file__).resolve().parents[3]
            logs_dir = root / "artifacts" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_file = logs_dir / f"broken_ai_json_{stage}_{ts}.txt"
            body = text or ""
            out_file.write_text(
                "\n".join([
                    f"timestamp={datetime.now().isoformat()}",
                    f"stage={stage}",
                    "",
                    "=== preview(1000) ===",
                    body[:1000],
                    "",
                    "=== full_response ===",
                    body,
                ]),
                encoding="utf-8",
            )
            print(f"⚠️ 已保存无法解析响应: {out_file}")
            return out_file
        except Exception:
            return None

    def _parse_json_safely(self, text: str) -> dict:
        """
        安全解析 JSON，自动修复常见格式问题
        
        Args:
            text: 可能包含 JSON 的文本
            
        Returns:
            解析后的字典
        """
        import re
        
        def ensure_dict(result):
            """确保返回结果是字典，处理AI返回数组的情况"""
            if isinstance(result, dict):
                return result
            elif isinstance(result, list):
                # AI 可能返回 [{...}] 而不是 {...}
                if len(result) == 1 and isinstance(result[0], dict):
                    print("⚠️ AI 返回了数组包装的对象，自动提取第一个元素")
                    return result[0]
                elif len(result) > 0 and isinstance(result[0], dict):
                    # 多个对象，取第一个
                    print(f"⚠️ AI 返回了包含 {len(result)} 个对象的数组，使用第一个")
                    return result[0]
                else:
                    raise ValueError(f"AI 返回了无法处理的数组格式: {type(result[0]) if result else 'empty'}")
            else:
                raise ValueError(f"AI 返回了非字典/数组类型: {type(result)}")
        
        # 首先尝试直接解析
        try:
            return ensure_dict(json.loads(text))
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 解析失败，尝试修复: {e}")
        
        # 清理文本
        cleaned = text.strip()
        
        # 移除可能的 markdown 代码块标记
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        # 尝试解析清理后的文本
        try:
            return ensure_dict(json.loads(cleaned))
        except json.JSONDecodeError:
            pass
        
        # 修复常见问题：replacement 中的未转义引号
        # 查找 "replacement": "..." 模式，修复内部未转义的引号
        def fix_replacement_quotes(match):
            prefix = match.group(1)
            content = match.group(2)
            suffix = match.group(3)
            
            # 转义内部的双引号（但不转义已经转义的）
            fixed_content = ""
            i = 0
            while i < len(content):
                if content[i] == '\\' and i + 1 < len(content):
                    fixed_content += content[i:i+2]
                    i += 2
                elif content[i] == '"':
                    fixed_content += '\\"'
                    i += 1
                else:
                    fixed_content += content[i]
                    i += 1
            
            return prefix + fixed_content + suffix
        
        # 尝试修复 replacement 字段中的引号问题
        try:
            # 这个正则可能不完美，但能处理大多数情况
            pattern = r'("replacement"\s*:\s*")([^"]*(?:\\.[^"]*)*)(")'
            fixed = re.sub(pattern, fix_replacement_quotes, cleaned)
            return ensure_dict(json.loads(fixed))
        except (json.JSONDecodeError, re.error):
            pass
        
        # 尝试提取 JSON 对象
        try:
            # 找到第一个 { 和最后一个 }
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = cleaned[start:end+1]
                return ensure_dict(json.loads(json_str))
        except json.JSONDecodeError:
            pass
        
        # 额外修复：处理字符串中的未转义引号/换行
        def repair_json_string_literals(raw: str) -> str:
            """
            修复 AI 常见输出问题：
            1) 字符串内出现未转义双引号
            2) 字符串内直接出现换行符
            """
            out: list[str] = []
            in_string = False
            escaped = False
            i = 0
            length = len(raw)

            while i < length:
                ch = raw[i]

                if not in_string:
                    if ch == '"':
                        in_string = True
                    out.append(ch)
                    i += 1
                    continue

                # in_string == True
                if escaped:
                    out.append(ch)
                    escaped = False
                    i += 1
                    continue

                if ch == '\\':
                    out.append(ch)
                    escaped = True
                    i += 1
                    continue

                if ch == '\n':
                    out.append("\\n")
                    i += 1
                    continue

                if ch == '\r':
                    # 统一丢弃 CR，避免与 \n 组合造成重复
                    i += 1
                    continue

                if ch == '"':
                    # 判断是字符串结束，还是正文中的未转义引号
                    j = i + 1
                    while j < length and raw[j] in (' ', '\t', '\n', '\r'):
                        j += 1

                    if j < length and raw[j] in [',', '}', ']']:
                        # 这是合法的字符串结束引号
                        out.append(ch)
                        in_string = False
                    else:
                        # 视为字符串正文中的引号，转义
                        out.append('\\"')
                    i += 1
                    continue

                out.append(ch)
                i += 1

            return "".join(out)

        try:
            repaired = repair_json_string_literals(cleaned)
            return ensure_dict(json.loads(repaired))
        except json.JSONDecodeError:
            pass

        # 最后的尝试：使用更宽松的解析
        try:
            # 替换一些常见问题
            relaxed = cleaned
            # 修复尾随逗号
            relaxed = re.sub(r',\s*}', '}', relaxed)
            relaxed = re.sub(r',\s*]', ']', relaxed)
            # 修复单引号
            relaxed = relaxed.replace("'", '"')
            # 修复缺失的逗号：} 或 ] 后面直接跟 { 或 " 或 [
            relaxed = re.sub(r'}\s*"', '}, "', relaxed)
            relaxed = re.sub(r'}\s*{', '}, {', relaxed)
            relaxed = re.sub(r']\s*"', '], "', relaxed)
            relaxed = re.sub(r']\s*\[', '], [', relaxed)
            # 修复数值/字符串后缺失逗号的情况: "value"\n"key" -> "value",\n"key"
            relaxed = re.sub(r'"\s*\n\s*"', '",\n"', relaxed)
            relaxed = repair_json_string_literals(relaxed)
            return ensure_dict(json.loads(relaxed))
        except json.JSONDecodeError:
            pass
        
        # 如果所有尝试都失败，先落盘再抛错
        self._dump_broken_json_response(text, stage="parse_failed")
        raise ValueError(f"无法解析 AI 响应的 JSON。响应前500字符: {text[:500]}")
    
    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI API"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        # 兼容不同中转/SDK返回格式：
        # 1) 标准 OpenAI 对象: response.choices[0].message.content
        # 2) dict 结构: {"choices":[{"message":{"content":"..."}}]}
        # 3) 直接字符串: '{"modifications":[...]}'
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                content = message.get("content")
                if isinstance(content, str):
                    return content
            # 兜底：部分中转会把内容直接放在 content/text 字段
            direct_content = response.get("content") or response.get("text")
            if isinstance(direct_content, str):
                return direct_content
            raise ValueError(f"无法从字典响应中提取内容，keys={list(response.keys())}")

        choices = getattr(response, "choices", None)
        if choices and len(choices) > 0:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None) if message else None
            if isinstance(content, str):
                return content

        raise ValueError(f"无法识别的 OpenAI 响应类型: {type(response)}")

    def _repair_json_with_llm(self, raw_text: str) -> Optional[dict]:
        """
        当本地 JSON 修复失败时，调用一次模型做“纯修复”。
        仅允许输出合法 JSON，不允许改写字段语义。
        """
        if not raw_text or not raw_text.strip():
            return None

        repair_system_prompt = (
            "You are a strict JSON repair engine. "
            "Your only task is to transform broken JSON-like text into valid JSON. "
            "Do not add commentary. Output JSON only."
        )
        repair_user_prompt = f"""Fix this broken JSON-like content to valid JSON.
Rules:
1) Keep original keys and values as much as possible.
2) Escape invalid quotes/newlines in string values.
3) Remove trailing commas and fix missing commas/brackets.
4) Return ONLY JSON object/array text.

Input:
{raw_text}
"""
        try:
            repaired_text = self._call_openai(repair_system_prompt, repair_user_prompt)
            return self._parse_json_safely(repaired_text)
        except Exception:
            self._dump_broken_json_response(raw_text, stage="llm_repair_failed")
            return None

    @staticmethod
    def _english_word_count(text: str) -> int:
        """Rough English word count for cover-letter length checks."""
        if not text or not text.strip():
            return 0
        return len(re.findall(r"[A-Za-z][A-Za-z0-9'-]*", text))

    def generate_cover_letter_english(
        self,
        job_description: str,
        resume_text: str,
        *,
        company_name: str,
        job_title: str,
        job_summary: str = "",
        applicant_full_name: str = "",
        jd_max_chars: int = 14000,
        resume_max_chars: int = 8000,
        summary_max_chars: int = 2000,
    ) -> str:
        """
        One-shot English cover letter (150–300 words) tailored to JD + resume,
        including required mobility / work-authorization facts.
        """
        cover_system = """You write professional cover letters in English for technical and knowledge-work roles.

Hard requirements:
1) The full letter MUST be between 150 and 300 words (count every word in the final letter body).
2) Plain text only. No Markdown, no bullet lists, no subject line. Use normal paragraphs separated by blank lines.
3) Opening: use "Dear Hiring Manager," unless the provided company name is clearly a real employer name (not "Unknown Company"); in that case you may use "Dear {Company} Team," only when the company name is plausible.
4) The letter MUST reflect the job description (JD): pick 2–4 concrete themes, requirements, or problems from the posting and connect them to specific experience or skills visible in the resume excerpt. Do not invent degrees, employers, or tools the resume does not support.
5) You MUST naturally weave in ALL of the following factual statements (one or two sentences, not as a checklist):
   - The candidate currently splits their time between Switzerland and Germany.
   - Their German residence authorization is the Opportunity Card (Chancenkarte), which is a national Category D visa that allows employment in Germany, and they are available to start on short notice.
   - They do not currently hold a Swiss work permit.
   - They are open to relocation and to fully remote or hybrid arrangements.
6) If a sign-off name is provided, end with "Sincerely," then a new line with that full name. If no name is provided, end with "Sincerely," only.
7) Output MUST be a single JSON object with exactly one key: "cover_letter" whose value is the full letter text (use \\n for newlines inside the JSON string)."""

        def _build_user(
            jd: str,
            resume: str,
            company: str,
            title: str,
            summary: str,
            name: str,
            retry_hint: str = "",
        ) -> str:
            name_line = (
                f"Sign with this full name after Sincerely: {name.strip()}"
                if (name or "").strip()
                else "No sign-off name provided — end with Sincerely, only (no name line)."
            )
            retry_block = f"\n## Length fix\n{retry_hint}\n" if retry_hint else ""
            return f"""## Job description
{jd}

## Resume excerpt (may be truncated)
{resume}

## Role fields (from analysis; use for addressing and alignment)
Company name: {company}
Job title: {title}
Brief job summary (for alignment, optional): {summary}

## Sign-off
{name_line}
{retry_block}
Return JSON: {{"cover_letter": "<full letter>"}}"""

        jd = (job_description or "")[:jd_max_chars]
        resume = (resume_text or "")[:resume_max_chars]
        summary = (job_summary or "")[:summary_max_chars]
        company = company_name or "Unknown Company"
        title = job_title or "Unknown Position"

        user_prompt = _build_user(jd, resume, company, title, summary, applicant_full_name)
        raw = self._call_openai(cover_system, user_prompt)
        try:
            data = self._parse_json_safely(raw)
        except ValueError:
            repaired = self._repair_json_with_llm(raw)
            if repaired is None:
                raise
            data = repaired

        letter = (data.get("cover_letter") or data.get("coverLetter") or "").strip()
        if not letter:
            raise ValueError("AI returned empty cover_letter")

        # Strip accidental fences if the model ignored instructions
        if letter.startswith("```"):
            letter = re.sub(r"^```[a-zA-Z]*\s*", "", letter)
            letter = re.sub(r"\s*```$", "", letter).strip()

        wc = self._english_word_count(letter)
        if 150 <= wc <= 300:
            return letter

        retry_hint = (
            f"Your previous draft was about {wc} words. The letter MUST be between 150 and 300 words total. "
            f"Rewrite the entire letter: keep all required mobility/visa facts and JD alignment, adjust length only. "
            f"Previous draft:\n{letter}"
        )
        user_retry = _build_user(jd, resume, company, title, summary, applicant_full_name, retry_hint=retry_hint)
        raw2 = self._call_openai(cover_system, user_retry)
        try:
            data2 = self._parse_json_safely(raw2)
        except ValueError:
            repaired2 = self._repair_json_with_llm(raw2)
            data2 = repaired2 or {}
        letter2 = (data2.get("cover_letter") or data2.get("coverLetter") or "").strip()
        if letter2.startswith("```"):
            letter2 = re.sub(r"^```[a-zA-Z]*\s*", "", letter2)
            letter2 = re.sub(r"\s*```$", "", letter2).strip()
        if letter2:
            wc2 = self._english_word_count(letter2)
            if 150 <= wc2 <= 300:
                return letter2
            # Accept retry if closer, else return best effort (still English + JD)
            if abs(wc2 - 225) < abs(wc - 225):
                return letter2
        return letter

    def analyze(self, job_description: str, resume_text: str) -> AnalysisResult:
        """
        分析岗位描述和简历，生成修改指令
        
        Args:
            job_description: 岗位描述
            resume_text: 简历文本内容
            
        Returns:
            AnalysisResult 对象
        """
        checklist_block = extract_jd_keyword_checklist(job_description)
        user_prompt = f"""## JD keyword checklist (pre-extracted from posting)
Aim to **naturally reflect** these JD terms where truthful—via experience bullets and skills—not by keyword stuffing.
{checklist_block}

## Job Description
{job_description}

## Resume Content
{resume_text}

## Additional Capabilities (candidate's unlisted but real skills just as example, u just also can imagine some others based on the JD and the existing resume content, as long as you think they are very likely to be possessed by the candidate and can be naturally integrated into the resume, then you can also weave them in, just be careful to keep the authenticity and naturalness of the resume, don't just pile up everything from JD and Additional Capabilities, that will make it look very fake and forced, remember we want to make it look like I naturally have these skills and experiences that fit the JD like a treasure, not like I am desperately trying to match the JD by adding everything)
The candidate has these additional capabilities that are NOT prominently featured in the resume above. You may selectively incorporate them if they strongly match the JD:
{ADDITIONAL_CAPABILITIES}

Please analyze the above content and generate modification instructions to optimize the resume. Remember:
1. target must be ACTUAL TEXT from the resume (not descriptive text so we can do the exact search)
2. target should be unique, easy-to-locate short text fragments (10-100 characters)
3. replacement length should be similar to target, not drastically different
4. You CAN add new bullet points using "add_after" match_type
5. You CAN rewrite entire bullets using "replace_paragraph" match_type
6. Use match_type: "fuzzy" for most replacements to improve success rate
7. **CRITICAL for add_after**: Use the LAST bullet in a section as anchor (new content at bottom). NEVER use first bullet as anchor!
8. **Flexible emphasis**: You can shift the focus of existing experiences to better match JD, and selectively weave in Additional Capabilities when highly relevant
9. **70-30 rule**: ~70% enhance existing content, at most 30% introduce your understand about I can have or new emphasis from Additional Capabilities(which just need to be perfectly matched with JD and can be naturally integrated, not forced, u can imageine some others that are not listed in Additional Capabilities but you judge I can also have based on my existing experience and the JD requirements, then you can also weave them in, just be careful to keep the authenticity and naturalness of the resume, don't just pile up everything from JD and Additional Capabilities, that will make it look very fake and forced, remember we want to make it look like I naturally have these skills and experiences that fit the JD like a treasure, not like I am desperately trying to match the JD by adding everything)
10. Return valid JSON format

Examples of correct usage:
- ✅ fuzzy (skill list): target: "AI & GenAI: Multi-Agent Systems, Graph RAG" → replacement: "**AI & GenAI:** Multi-Agent Systems, **Simulation automation**, Graph RAG" (category label bold, selected terms bold)
- ✅ fuzzy (skill list): target: "Languages: English (C1), Mandarin (Native)" → replacement: "**Languages:** English (C1 - Professional), Mandarin (Native), German (A2 - Basic)" (only category label bold)
- ✅ fuzzy (bullet): target: "Developed ML models" → replacement: "Developed **ML models** and delivered **customer prototypes**"
- ✅ add_after: target: "Led the development of AI City" → replacement: "• **Customer Collaboration:** Worked directly with **customers**..." (bullet symbol required, leading phrase bold)
- ✅ replace_paragraph: target: "Built backend infrastructure" → replacement: "• **Cloud-Native DevOps & Service Delivery:** Built backend with **FastAPI**..." (leading phrase + tech terms bold)
- ❌ add_after with missing bullet: replacement: "Customer Collaboration: Worked..." (must include • at start)
- ❌ add_after with non-bold leading phrase: replacement: "• Customer Collaboration: Worked..." (leading phrase must be bold!)
- ❌ fuzzy (skill list) with non-bold category: replacement: "AI & GenAI: Multi-Agent Systems..." (category label must be bold!)
- ❌ target: "Z. AI - Core developer for 'AI City'" (might not be exact resume text)
- ❌ target: "Add this bullet point" (not actual text from resume)


"""
        
        result_text = self._call_openai(SYSTEM_PROMPT, user_prompt)
        
        # 尝试解析 JSON，如果失败则触发一次 LLM 修复兜底
        try:
            result_json = self._parse_json_safely(result_text)
        except ValueError:
            repaired = self._repair_json_with_llm(result_text)
            if repaired is None:
                raise
            print("⚠️ 本地 JSON 修复失败，已通过 LLM 修复响应")
            result_json = repaired
        
        # 转换为 AnalysisResult
        modifications = [
            ModificationInstruction(
                target=m.get("target", ""),
                replacement=m.get("replacement", ""),
                reason=m.get("reason", ""),
                priority=m.get("priority", "medium"),
                match_type=m.get("match_type", "fuzzy")  # 默认使用fuzzy匹配
            )
            for m in result_json.get("modifications", [])]
        
        # 自动修正：确保前导语加粗
        modifications = self._auto_fix_bold_formatting(modifications)
        
        return AnalysisResult(
            job_summary=result_json.get("job_summary", ""),
            modifications=modifications,
            suggestions=result_json.get("suggestions", []),
            match_score=result_json.get("match_score", 0),
            company_name=result_json.get("company_name", "Unknown Company"),
            job_title=result_json.get("job_title", "Unknown Position")
        )
    
    def _auto_fix_bold_formatting(self, modifications: List[ModificationInstruction]) -> List[ModificationInstruction]:
        """
        自动修正replacement文本，确保前导语加粗
        
        规则：
        1. 如果replacement以bullet符号(•)开头且冒号前的文本没有加粗，自动加粗
        2. 如果replacement是技能列表（冒号前的类别标签）没有加粗，自动加粗
        """
        import re
        
        fixed_modifications = []
        for mod in modifications:
            replacement = mod.replacement.strip()
            
            # 检查是否需要修正
            needs_fix = False
            fixed_replacement = replacement
            
            # 情况1: bullet点开头 (• xxx: ...)
            if replacement.startswith(('• ', '- ', '* ', '○ ', '▪ ')):
                # 提取bullet符号
                bullet_char = replacement[0]
                content = replacement[1:].strip()
                
                # 使用正则检查格式：应该是 **text**: 或 text:
                # 正确格式: **Graph RAG Development**: ...
                # 错误格式: Graph RAG Development: ... 或 **Graph RAG**: ...** ...
                
                bold_colon_pattern = r'^\*\*([^*]+)\*\*:'
                plain_colon_pattern = r'^([^:*]+):'
                
                bold_match = re.match(bold_colon_pattern, content)
                plain_match = re.match(plain_colon_pattern, content)
                
                if bold_match:
                    # 已经是正确的 **text**: 格式，无需修正
                    pass
                elif plain_match:
                    # 是 text: 格式，需要加粗
                    leading_text = plain_match.group(1).strip()
                    rest_text = content[plain_match.end():]
                    fixed_replacement = f"{bullet_char} **{leading_text}:**{rest_text}"
                    needs_fix = True
            
            # 情况2: 技能类别标签开头 (Category: ...) - 不以bullet符号开头
            elif not replacement.startswith(('• ', '- ', '* ', '○ ', '▪ ', ' ')) and ':' in replacement:
                # 使用正则检查格式
                bold_colon_pattern = r'^\*\*([^*]+)\*\*:'
                plain_colon_pattern = r'^([^:*]+):'
                
                bold_match = re.match(bold_colon_pattern, replacement)
                plain_match = re.match(plain_colon_pattern, replacement)
                
                if bold_match:
                    # 已经是正确的 **text**: 格式，无需修正
                    pass
                elif plain_match:
                    # 是 text: 格式，需要加粗
                    leading_text = plain_match.group(1).strip()
                    rest_text = replacement[plain_match.end():]
                    fixed_replacement = f"**{leading_text}:**{rest_text}"
                    needs_fix = True
            
            # 创建修正后的指令
            if needs_fix:
                fixed_modifications.append(ModificationInstruction(
                    target=mod.target,
                    replacement=fixed_replacement,
                    reason=mod.reason,
                    priority=mod.priority,
                    match_type=mod.match_type
                ))
            else:
                fixed_modifications.append(mod)
        
        return fixed_modifications
    
    def analyze_with_context(
        self, 
        job_description: str, 
        resume_text: str,
        additional_context: Optional[str] = None,
        focus_areas: Optional[List[str]] = None
    ) -> AnalysisResult:
        """
        带额外上下文的分析
        
        Args:
            job_description: 岗位描述
            resume_text: 简历文本内容
            additional_context: 额外的上下文信息（如用户偏好）
            focus_areas: 重点关注的领域（如 ["地点", "技能"]）
            
        Returns:
            AnalysisResult 对象
        """
        context_parts = []
        
        if additional_context:
            context_parts.append(f"## 额外说明\n{additional_context}")
        
        if focus_areas:
            context_parts.append(f"## 重点关注\n请特别注意以下方面的修改：{', '.join(focus_areas)}")
        
        enhanced_job_description = job_description
        if context_parts:
            enhanced_job_description += "\n\n" + "\n\n".join(context_parts)
        
        return self.analyze(enhanced_job_description, resume_text)

    def answer_application_questions(self, page_text: str, resume_text: str) -> List[Dict[str, str]]:
        """
        从页面内容中提取申请问题，并结合简历生成个性化答案
        
        Args:
            page_text: 页面文本内容（可能包含申请问题）
            resume_text: 简历文本内容
            
        Returns:
            问题-答案列表 [{"question": "...", "answer": "..."}, ...]
        """
        qa_system_prompt = """You are a professional job application assistant. Your task is to:

1. **Extract application questions** from the page content. Common questions include:
   - "Why do you want to work for our company?"
   - "Why are you interested in this position?"
   - "What are your salary expectations?"
   - "What is your earliest start date?"
   - "Do you have experience with [specific technology]?"
   - "Describe a challenging project you worked on"
   - "What are your strengths/weaknesses?"
   - Cover letter / motivational letter prompts
   - Any text input field labels that appear to be questions

2. **Generate personalized answers** based on the candidate's resume. Answers should:
   - Be professional, genuine, and tailored to the specific company/role
   - Highlight relevant experience and skills from the resume
   - Be concise but comprehensive (150-300 words for longer questions, 50-100 words for shorter ones)
   - Sound natural, not overly generic or AI-generated
   - Be in the same language as the question (if the question is in German, answer in German)

3. **Important rules:**
   - Only extract genuine questions that require a written response
   - Skip yes/no checkboxes, dropdowns, or date pickers
   - If no questions are found, return an empty array
   - Focus on quality over quantity

## Output Format
Return JSON format:
```json
{
    "questions": [
        {
            "question": "Why are you interested in this position?",
            "answer": "I am excited about this opportunity because..."
        },
        {
            "question": "What are your salary expectations?",
            "answer": "Based on my experience and the market rate..."
        }
    ]
}
```

If no questions are found, return:
```json
{
    "questions": []
}
```
"""

        user_prompt = f"""## Page Content (may contain application form questions)
{page_text}

## Candidate's Resume
{resume_text}

Please analyze the page content to identify any application questions, and generate personalized answers based on the resume. Return the results in JSON format.
"""

        result_text = self._call_openai(qa_system_prompt, user_prompt)
        
        # 解析响应（使用安全解析 + LLM 修复兜底）
        try:
            result_json = self._parse_json_safely(result_text)
        except ValueError:
            repaired = self._repair_json_with_llm(result_text)
            if repaired is None:
                raise
            print("⚠️ QA JSON 本地修复失败，已通过 LLM 修复响应")
            result_json = repaired
        
        return result_json.get("questions", [])


def analyze_resume(
    job_description: str,
    resume_text: str,
    api_key: Optional[str] = None
) -> AnalysisResult:
    """
    便捷函数：分析简历
    
    Args:
        job_description: 岗位描述
        resume_text: 简历文本
        api_key: 可选的 API 密钥
        
    Returns:
        AnalysisResult 对象
    """
    analyzer = AIAnalyzer(api_key=api_key)
    return analyzer.analyze(job_description, resume_text)


if __name__ == "__main__":
    # 测试代码
    test_job = "需要一个工作经历都是在中国的AI开发工程师，要求5年以上经验"
    test_resume = """
    Candidate Name
    AI Developer
    
    Work Experience:
    - Greenzero GmbH, Berlin (2022-2024)
      Senior AI Developer
      - Developed machine learning models
      - 3 years of experience in Python
    
    Education:
    - Master of Computer Science, TU Berlin
    """
    
    try:
        result = analyze_resume(test_job, test_resume)
        print("分析结果:")
        print(f"岗位总结: {result.job_summary}")
        print(f"匹配度: {result.match_score}%")
        print(f"\n修改指令 ({len(result.modifications)} 条):")
        for m in result.modifications:
            print(f"  [{m.priority}] {m.target} -> {m.replacement}")
            print(f"         原因: {m.reason}")
        print(f"\n建议:")
        for s in result.suggestions:
            print(f"  - {s}")
    except Exception as e:
        print(f"分析失败: {e}")

