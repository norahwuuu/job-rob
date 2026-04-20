#!/usr/bin/env python3
"""
LinkedIn 智能求职助手 - 统一入口
整合三个项目：LinkedIn-Collect, word_editor, auto-apply-project

使用方法:
    python run_pipeline.py              # 完整流程
    python run_pipeline.py crawl        # 只爬取岗位
    python run_pipeline.py generate     # 只生成定制简历
    python run_pipeline.py rescore-llm  # 对 jobs_progress 中 LLM 评分失败的记录重新评分
    python run_pipeline.py apply        # Easy Apply：生成填表 JSON + 默认浏览器投递
    python run_pipeline.py status       # 查看进度
    python run_pipeline.py done 001     # 标记手动申请完成
    python run_pipeline.py open         # 打开输出文件夹
"""

import os
import sys
import json
import yaml
import time
import shutil
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Tuple
import subprocess
from urllib.parse import urlparse, urlunparse

# ============================================================
# 日志配置
# ============================================================
log = logging.getLogger("pipeline")
log.setLevel(logging.DEBUG)
log.propagate = False

# 控制台输出
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S'))
log.addHandler(console_handler)

# 文件输出（统一放到根目录 artifacts/logs，避免受运行目录影响）
LOG_DIR = Path(__file__).parent.parent / "artifacts" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(str(LOG_DIR / f'pipeline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'), encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
log.addHandler(file_handler)


# ============================================================
# 状态与产物语义
# ============================================================
STATUS_DISCOVERED = "discovered"
STATUS_RESUME_READY = "resume_ready"
STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_CLOSED = "closed"
ALLOWED_CANONICAL_STATUSES = {
    STATUS_DISCOVERED,
    STATUS_RESUME_READY,
    STATUS_APPLIED,
    STATUS_SKIPPED,
    STATUS_FAILED,
    STATUS_CLOSED,
}

LEGACY_STATUS_ALIASES = {
    "pending": STATUS_DISCOVERED,
    "resume_generated": STATUS_RESUME_READY,
}

CANONICAL_STATUS_PRIORITY = {
    STATUS_APPLIED: 5,
    STATUS_CLOSED: 4,
    STATUS_FAILED: 3,
    STATUS_RESUME_READY: 2,
    STATUS_DISCOVERED: 1,
}

PENDING_LIFECYCLE_STATUSES = {STATUS_DISCOVERED, STATUS_RESUME_READY}
TERMINAL_LIFECYCLE_STATUSES = {STATUS_APPLIED, STATUS_SKIPPED, STATUS_CLOSED}


def normalize_job_status(status: Any, default: str = STATUS_DISCOVERED) -> str:
    """将旧状态值映射到新的 canonical 状态。"""
    value = str(status or "").strip()
    if not value:
        return default
    normalized = LEGACY_STATUS_ALIASES.get(value, value)
    return normalized if normalized in ALLOWED_CANONICAL_STATUSES else default


def is_pending_lifecycle_status(status: Any) -> bool:
    return normalize_job_status(status) in PENDING_LIFECYCLE_STATUSES


def is_terminal_lifecycle_status(status: Any) -> bool:
    return normalize_job_status(status) in TERMINAL_LIFECYCLE_STATUSES


def status_sort_priority(status: Any) -> int:
    return CANONICAL_STATUS_PRIORITY.get(normalize_job_status(status), 0)


def normalize_openai_base_url(raw_url: str) -> str:
    """
    规范化 OpenAI 兼容接口 base_url。
    - 自动去除尾部 /chat/completions（如果误填了完整接口）
    - 自动补齐 /v1（如果只填了域名）
    """
    url = (raw_url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url

    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if not path:
        path = "/v1"
    elif not path.endswith("/v1"):
        path = f"{path}/v1"

    return urlunparse(parsed._replace(path=path))


# ============================================================
# Token 计费追踪
# ============================================================
@dataclass
class TokenUsage:
    """Token使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    api_calls: int = 0
    
    # Gemini 3 Flash 价格 (USD per 1M tokens)
    # https://ai.google.dev/pricing
    GEMINI_FLASH_INPUT_PRICE = 0.075   # $0.075 per 1M input tokens
    GEMINI_FLASH_OUTPUT_PRICE = 0.30   # $0.30 per 1M output tokens
    
    # GPT-4 价格
    GPT4_INPUT_PRICE = 30.0   # $30 per 1M input tokens
    GPT4_OUTPUT_PRICE = 60.0  # $60 per 1M output tokens
    
    def add_usage(self, input_tokens: int, output_tokens: int, model: str = "gemini-3-flash-preview"):
        """添加一次API调用的token使用"""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.api_calls += 1
        
        # 计算费用
        if "gemini" in model.lower():
            input_cost = (input_tokens / 1_000_000) * self.GEMINI_FLASH_INPUT_PRICE
            output_cost = (output_tokens / 1_000_000) * self.GEMINI_FLASH_OUTPUT_PRICE
        elif "gpt-4" in model.lower():
            input_cost = (input_tokens / 1_000_000) * self.GPT4_INPUT_PRICE
            output_cost = (output_tokens / 1_000_000) * self.GPT4_OUTPUT_PRICE
        else:
            # 默认按Gemini价格
            input_cost = (input_tokens / 1_000_000) * self.GEMINI_FLASH_INPUT_PRICE
            output_cost = (output_tokens / 1_000_000) * self.GEMINI_FLASH_OUTPUT_PRICE
            
        self.estimated_cost_usd += input_cost + output_cost
        
        log.debug(f"Token使用: +{input_tokens} input, +{output_tokens} output, 累计费用: ${self.estimated_cost_usd:.4f}")
    
    def print_summary(self):
        """打印token使用汇总"""
        print("\n" + "=" * 50)
        print("💰 API Token 使用统计")
        print("=" * 50)
        print(f"API调用次数: {self.api_calls}")
        print(f"输入 tokens: {self.input_tokens:,}")
        print(f"输出 tokens: {self.output_tokens:,}")
        print(f"总计 tokens: {self.total_tokens:,}")
        print(f"预估费用: ${self.estimated_cost_usd:.4f} USD (约 ¥{self.estimated_cost_usd * 7.2:.2f})")
        print("=" * 50)
    
    def to_dict(self) -> dict:
        return {
            'api_calls': self.api_calls,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'total_tokens': self.total_tokens,
            'estimated_cost_usd': round(self.estimated_cost_usd, 4)
        }


# 全局token计数器
token_tracker = TokenUsage()


# ============================================================
# 配置管理
# ============================================================
class ConfigManager:
    """统一配置管理器 - 同步更新三个项目的配置"""
    
    def __init__(self, config_path: str = "pipeline_config.yaml"):
        self.base_dir = Path(__file__).parent
        config_candidate = Path(config_path)
        if not config_candidate.is_absolute():
            config_candidate = (self.base_dir / config_candidate).resolve()
        self.config_path = config_candidate
        
        # 项目路径
        self.LINKEDIN_COLLECT_PATH = self.base_dir
        # 指向 word_editor 根目录（兼容目录名可能带 "-main"）
        parent_dir = self.base_dir.parent
        candidate_word_editor_paths = [
            parent_dir / "resume_AI_editor" / "word_editor",
            parent_dir / "resume-customizer" / "word_editor",
        ]
        self.WORD_EDITOR_PATH = next(
            (p for p in candidate_word_editor_paths if p.exists()),
            candidate_word_editor_paths[0],
        )
        self.AUTO_APPLIER_PATH = self.base_dir.parent / "auto-apply-project"
        
        self.config = self._load_config()
        
    def _load_config(self) -> dict:
        """加载统一配置"""
        self._load_local_env_file()
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                self._resolve_env_placeholders(config)
                self._apply_env_overrides(config)
                self._apply_pipeline_env_overrides(config)
                self._apply_profile_overrides(config)
                return config
        else:
            log.warning(f"配置文件 {self.config_path} 不存在，使用默认配置")
            config = self._default_config()
            self._apply_env_overrides(config)
            self._apply_pipeline_env_overrides(config)
            self._apply_profile_overrides(config)
            return config

    def _resolve_env_placeholders(self, data):
        """将 ${ENV_KEY} 占位符解析为环境变量值（未设置则置空字符串）"""
        if isinstance(data, dict):
            for key, value in data.items():
                data[key] = self._resolve_env_placeholders(value)
            return data
        if isinstance(data, list):
            return [self._resolve_env_placeholders(item) for item in data]
        if isinstance(data, str):
            m = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", data.strip())
            if m:
                return os.environ.get(m.group(1), "")
        return data

    def _load_local_env_file(self):
        """加载本地环境变量文件（优先仓库根目录 .env）。"""
        env_files = [
            self.base_dir.parent / ".env",
            self.base_dir / ".env",
        ]

        for env_path in env_files:
            if not env_path.exists():
                continue
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = self._strip_env_inline_comment(value).strip().strip('"').strip("'")
                        if key:
                            os.environ[key] = value
            except Exception as e:
                log.warning(f"读取 {env_path.name} 失败: {e}")

    def _strip_env_inline_comment(self, value: str) -> str:
        """去掉 .env 值中的行尾注释（保留引号内的 #）"""
        text = value.rstrip()
        in_single = False
        in_double = False
        for i, ch in enumerate(text):
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "#" and not in_single and not in_double:
                return text[:i].rstrip()
        return text

    def _apply_env_overrides(self, config: dict):
        """用环境变量覆盖配置（含 profile 全字段）"""
        linkedin = config.setdefault("linkedin", {})
        ai = config.setdefault("ai", {})
        profile = config.setdefault("profile", {})

        # 统一个人信息来源：优先使用 PERSONAL_*，并兼容旧键
        env_aliases = {
            ("profile", "full_name"): ["PERSONAL_FULL_NAME", "PROFILE_FULL_NAME"],
            ("profile", "first_name"): ["PERSONAL_FIRST_NAME", "PROFILE_FIRST_NAME"],
            ("profile", "email"): ["PERSONAL_EMAIL", "PROFILE_EMAIL", "LINKEDIN_USERNAME"],
            ("profile", "phone_number"): ["PERSONAL_PHONE_NUMBER", "PROFILE_PHONE_NUMBER", "LINKEDIN_PHONE_NUMBER"],
            ("profile", "resume_file_prefix"): ["PERSONAL_RESUME_FILE_PREFIX", "PROFILE_RESUME_FILE_PREFIX"],
            ("profile", "resume_output_prefix"): ["PERSONAL_RESUME_OUTPUT_PREFIX", "PROFILE_RESUME_OUTPUT_PREFIX"],
            ("linkedin", "password"): ["PERSONAL_LINKEDIN_PASSWORD", "LINKEDIN_PASSWORD"],
            ("ai", "gemini_api_key"): ["GEMINI_API_KEY"],
            ("ai", "openai_api_key"): ["OPENAI_API_KEY"],
            ("ai", "openai_base_url"): ["AI_SERVER_URL", "OPENAI_BASE_URL"],
        }

        target_map = {"linkedin": linkedin, "profile": profile, "ai": ai}
        for (section, field), aliases in env_aliases.items():
            for key in aliases:
                value = os.environ.get(key)
                if value:
                    target_map[section][field] = value
                    break

    def _apply_pipeline_env_overrides(self, config: dict):
        """
        用 PIPELINE__A__B 形式覆盖任意配置项。
        例:
        - PIPELINE__SEARCH__POSITIONS=["Frontend Engineer","React Engineer"]
        - PIPELINE__SEARCH__MAX_PAGES=1
        - PIPELINE__FILTER__MIN_AI_SCORE=60
        """
        prefix = "PIPELINE__"
        for env_key, raw_value in os.environ.items():
            if not env_key.startswith(prefix):
                continue

            key_path = [p.lower() for p in env_key[len(prefix):].split("__") if p]
            if not key_path:
                continue

            parsed_value = self._parse_env_value(raw_value)
            self._set_nested_config_value(config, key_path, parsed_value)

    def _parse_env_value(self, raw_value: str):
        """将环境变量字符串转换为合理类型（bool/int/float/list/dict/str）"""
        text = (raw_value or "").strip()
        if text == "":
            return ""

        # 优先支持 YAML/JSON 风格值，如 true / 123 / [a,b] / {"k":1}
        try:
            parsed = yaml.safe_load(text)
            if isinstance(parsed, (bool, int, float, list, dict)):
                return parsed
        except Exception:
            pass

        # 兜底: 逗号分隔转列表
        if "," in text:
            return [item.strip() for item in text.split(",") if item.strip()]
        return text

    def _set_nested_config_value(self, config: dict, key_path: List[str], value):
        """按路径写入嵌套配置，如 ['search','max_pages']"""
        current = config
        for key in key_path[:-1]:
            node = current.get(key)
            if not isinstance(node, dict):
                node = {}
                current[key] = node
            current = node
        current[key_path[-1]] = value

    def _sync_scraper_config_from_effective(self, config: dict):
        """按最终生效配置写入 scraper_config.yaml（不落盘个人字段）。"""
        scraper_config_path = self.LINKEDIN_COLLECT_PATH / "scraper_config.yaml"
        if scraper_config_path.exists():
            with open(scraper_config_path, "r", encoding="utf-8") as f:
                scraper_config = yaml.safe_load(f) or {}
        else:
            scraper_config = {}

        scraper_config.pop("username", None)
        scraper_config.pop("password", None)
        scraper_config.pop("phone_number", None)

        search_cfg = config.get("search", {}) or {}
        filter_cfg = config.get("filter", {}) or {}
        advanced_cfg = config.get("advanced", {}) or {}
        resume_cfg = config.get("resume", {}) or {}
        ai_cfg = config.get("ai", {}) or {}

        scraper_config["positions"] = search_cfg.get("positions") or []
        scraper_config["locations"] = search_cfg.get("locations") or []
        locs = scraper_config["locations"] or []
        if locs and all(str(x).strip().lower() == "remote" for x in locs):
            scraper_config["distance"] = None
        scraper_config["geo_id"] = search_cfg.get("geo_id") or None
        scraper_config["time_filter"] = search_cfg.get("time_filter", "")
        scraper_config["sort_by"] = search_cfg.get("sort_by", "DD")
        scraper_config["max_pages"] = search_cfg.get("max_pages", 1)
        scraper_config["auto_resume"] = bool(search_cfg.get("auto_resume", True))
        scraper_config["experience_level"] = search_cfg.get("experience_level") or []

        scraper_config["max_experience_years"] = filter_cfg.get("max_experience_years")
        scraper_config["min_experience_years"] = filter_cfg.get("min_experience_years")
        scraper_config["exclude_title_keywords"] = filter_cfg.get("exclude_title_keywords") or []
        scraper_config["filter_german_jobs"] = bool(filter_cfg.get("exclude_german", True))

        scraper_config["headless"] = bool(advanced_cfg.get("headless", False))
        scraper_config["batch_size"] = advanced_cfg.get("batch_size", 25)
        scraper_config["llm_delay"] = advanced_cfg.get("llm_delay", 1.0)
        scraper_config["resume_path"] = resume_cfg.get("base_json", "resume.json")
        output_cfg = config.get("output", {}) or {}
        output_base = output_cfg.get("base_dir", "./output") or "./output"
        save_csv = bool(output_cfg.get("save_csv", False))
        scraper_config["save_csv"] = save_csv
        if save_csv:
            scraper_config["output_passed_csv"] = str(Path(output_base) / "jobs_passed.csv")
            scraper_config["output_filtered_csv"] = str(Path(output_base) / "jobs_filtered_out.csv")
        else:
            scraper_config["output_passed_csv"] = ""
            scraper_config["output_filtered_csv"] = ""
        scraper_config["output_json"] = str(Path(output_base) / "jobs_passed.json")

        scraper_config["gemini_api_key"] = ""
        scraper_config["gemini_model"] = ai_cfg.get("openai_model", "gemini-2.5-flash")
        scraper_config["ai_provider"] = "gemini_relay"
        scraper_config["openai_api_key"] = ai_cfg.get("openai_api_key", "")
        scraper_config["openai_model"] = ai_cfg.get("openai_model", "gemini-2.5-flash")
        scraper_config["openai_base_url"] = normalize_openai_base_url(
            ai_cfg.get("openai_base_url") or ai_cfg.get("server_url", "")
        )
        scraper_config["enable_pre_filter"] = bool(ai_cfg.get("enable_pre_filter", True))
        scraper_config["enable_ai_pre_filter"] = bool(ai_cfg.get("enable_ai_pre_filter", True))
        scraper_config["use_llm_scoring"] = bool(ai_cfg.get("use_llm_scoring", True))

        with open(scraper_config_path, "w", encoding="utf-8") as f:
            yaml.dump(scraper_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _default_config(self) -> dict:
        """默认配置"""
        return {
            'linkedin': {
                'username': '',
                'password': '',
                'phone_number': ''
            },
            'profile': {
                'full_name': '',
                'first_name': '',
                'email': '',
                'phone_number': '',
                'resume_file_prefix': 'Candidate_Resume',
                'resume_output_prefix': 'Candidate'
            },
            'ai': {
                'provider': 'gemini_relay',
                'gemini_api_key': '',
                'gemini_model': 'gemini-2.5-flash',
                'enable_pre_filter': True,
                'enable_ai_pre_filter': True,
                'use_llm_scoring': True,
                'openai_api_key': '',
                'openai_model': 'gemini-2.5-flash'
            },
            'resume': {
                'base_docx': './cv.docx',
                'base_json': './resume.json'
            },
            'filter': {
                'min_ai_score': 70,
                'max_experience_years': 5,
                'exclude_german': True
            },
            'output': {
                'base_dir': '../artifacts',
                'save_csv': False,
            }
        }

    def _apply_profile_overrides(self, config: dict):
        """用 profile 段统一覆盖非功能性个人信息字段（向后兼容旧配置）"""
        profile = config.get('profile', {}) or {}
        linkedin = config.setdefault('linkedin', {})

        email = profile.get('email')
        phone = profile.get('phone_number')
        if email:
            linkedin['username'] = email
        if phone:
            linkedin['phone_number'] = phone
    
    def sync_to_projects(self):
        """同步配置到三个项目"""
        log.info("同步配置到各项目...")
        
        # 1. 同步到 LinkedIn-Collect
        self._sync_linkedin_collect()
        
        # 2. 同步到 word_editor
        self._sync_word_editor()
        
        # 3. 同步到 Auto_job_applier
        self._sync_auto_applier()
        
        log.info("配置同步完成")
    
    def _sync_linkedin_collect(self):
        """同步到 LinkedIn-Collect 的 scraper_config.yaml"""
        scraper_config_path = self.LINKEDIN_COLLECT_PATH / "scraper_config.yaml"
        
        if scraper_config_path.exists():
            with open(scraper_config_path, 'r', encoding='utf-8') as f:
                scraper_config = yaml.safe_load(f) or {}
        else:
            scraper_config = {}
        
        # 个人敏感字段只保存在 pipeline_config.yaml，不落盘到 scraper_config.yaml
        scraper_config.pop('username', None)
        scraper_config.pop('password', None)
        scraper_config.pop('phone_number', None)

        # 同步搜索配置（确保 PIPELINE__SEARCH__* 覆盖后能生效）
        search_cfg = self.config.get('search', {}) or {}
        if 'positions' in search_cfg:
            scraper_config['positions'] = search_cfg.get('positions') or []
        if 'locations' in search_cfg:
            scraper_config['locations'] = search_cfg.get('locations') or []
            locs = scraper_config['locations'] or []
            if locs and all(str(x).strip().lower() == "remote" for x in locs):
                scraper_config["distance"] = None
        if 'geo_id' in search_cfg:
            scraper_config['geo_id'] = search_cfg.get('geo_id') or None
        if 'time_filter' in search_cfg:
            scraper_config['time_filter'] = search_cfg.get('time_filter', '')
        if 'sort_by' in search_cfg:
            scraper_config['sort_by'] = search_cfg.get('sort_by', 'DD')
        if 'max_pages' in search_cfg:
            scraper_config['max_pages'] = search_cfg.get('max_pages', 1)
        scraper_config['auto_resume'] = bool(search_cfg.get('auto_resume', True))
        if 'experience_level' in search_cfg:
            scraper_config['experience_level'] = search_cfg.get('experience_level') or []

        # 同步筛选配置
        filter_cfg = self.config.get('filter', {}) or {}
        if 'max_experience_years' in filter_cfg:
            scraper_config['max_experience_years'] = filter_cfg.get('max_experience_years')
        if 'min_experience_years' in filter_cfg:
            scraper_config['min_experience_years'] = filter_cfg.get('min_experience_years')
        if 'exclude_title_keywords' in filter_cfg:
            scraper_config['exclude_title_keywords'] = filter_cfg.get('exclude_title_keywords') or []

        # 同步高级配置
        advanced_cfg = self.config.get('advanced', {}) or {}
        if 'headless' in advanced_cfg:
            scraper_config['headless'] = bool(advanced_cfg.get('headless', False))
        if 'batch_size' in advanced_cfg:
            scraper_config['batch_size'] = advanced_cfg.get('batch_size', 25)
        if 'llm_delay' in advanced_cfg:
            scraper_config['llm_delay'] = advanced_cfg.get('llm_delay', 1.0)

        # 同步基础输出与简历配置
        resume_cfg = self.config.get('resume', {}) or {}
        if 'base_json' in resume_cfg:
            scraper_config['resume_path'] = resume_cfg.get('base_json', 'resume.json')
        output_cfg = self.config.get('output', {}) or {}
        output_base = output_cfg.get('base_dir', './output') or './output'
        save_csv = bool(output_cfg.get('save_csv', False))
        scraper_config['save_csv'] = save_csv
        if save_csv:
            scraper_config['output_passed_csv'] = str(Path(output_base) / 'jobs_passed.csv')
            scraper_config['output_filtered_csv'] = str(Path(output_base) / 'jobs_filtered_out.csv')
        else:
            scraper_config['output_passed_csv'] = ''
            scraper_config['output_filtered_csv'] = ''
        scraper_config['output_json'] = str(Path(output_base) / 'jobs_passed.json')

        ai_cfg = self.config.get('ai', {}) or {}
        scraper_config['gemini_api_key'] = ''
        scraper_config['gemini_model'] = ai_cfg.get('openai_model', 'gemini-2.5-flash')
        scraper_config['ai_provider'] = 'gemini_relay'
        scraper_config['openai_api_key'] = ai_cfg.get('openai_api_key', '')
        scraper_config['openai_model'] = ai_cfg.get('openai_model', 'gemini-2.5-flash')
        scraper_config['openai_base_url'] = normalize_openai_base_url(
            ai_cfg.get('openai_base_url') or ai_cfg.get('server_url', '')
        )
        scraper_config['enable_pre_filter'] = bool(ai_cfg.get('enable_pre_filter', True))
        scraper_config['enable_ai_pre_filter'] = bool(ai_cfg.get('enable_ai_pre_filter', True))
        scraper_config['use_llm_scoring'] = bool(ai_cfg.get('use_llm_scoring', True))
        
        with open(scraper_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(scraper_config, f, allow_unicode=True, default_flow_style=False)
        
        log.debug(f"已更新: {scraper_config_path}")
    
    def _sync_word_editor(self):
        """同步到 word_editor 的 .env"""
        if not self.WORD_EDITOR_PATH.exists():
            log.warning(f"word_editor 项目不存在: {self.WORD_EDITOR_PATH}")
            return
        
        # 更新 .env 文件 (位于 word_editor 根目录)
        # 注意: self.WORD_EDITOR_PATH 已修正为指向项目根目录
        env_path = self.WORD_EDITOR_PATH / ".env"
        env_content = f"""# Auto-synced from pipeline_config.yaml
# OPENAI_API_KEY is resolved from process environment at runtime.
AI_PROVIDER=gemini_relay
OPENAI_API_KEY=${{OPENAI_API_KEY}}
OPENAI_MODEL={self.config.get('ai', {}).get('openai_model', 'gemini-2.5-flash')}
OPENAI_BASE_URL={normalize_openai_base_url(self.config.get('ai', {}).get('openai_base_url') or self.config.get('ai', {}).get('server_url', ''))}
AI_SERVER_URL={normalize_openai_base_url(self.config.get('ai', {}).get('server_url') or self.config.get('ai', {}).get('openai_base_url', ''))}
"""
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        log.debug(f"已更新: {env_path}")
    
    def _sync_auto_applier(self):
        """同步到 auto-apply-project（当前无额外敏感配置文件需要同步）。"""
        if not self.AUTO_APPLIER_PATH.exists():
            log.warning(f"auto-apply-project 不存在: {self.AUTO_APPLIER_PATH}")
            return
        log.debug("auto-apply-project 使用 jobs_progress 输入，无需 secrets.py 同步")


# ============================================================
# 进度追踪
# ============================================================
@dataclass
class JobStatus:
    """岗位状态"""
    job_id: str
    title: str
    company: str
    ai_score: float
    is_easy_apply: bool
    url: str
    job_description: str = ""
    status: str = STATUS_DISCOVERED  # canonical: discovered, resume_ready, applied, skipped, failed, closed
    resume_path: str = ""
    applied_at: str = ""
    
    
class ProgressTracker:
    """进度追踪器（历史兼容层，主权威文件仍是 jobs_progress.json）。"""
    
    TRACKER_FILE = "application_tracker.json"
    APPLIED_FILE = "applied_jobs.json"
    
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = Path(output_dir)
        self.tracker_path = self.output_dir / self.TRACKER_FILE
        self.applied_path = self.output_dir / self.APPLIED_FILE
        self.jobs: Dict[str, JobStatus] = {}
        self._load()
    
    def _load(self):
        """加载进度"""
        if self.tracker_path.exists():
            try:
                with open(self.tracker_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for job_id, job_data in data.items():
                        job_data["status"] = normalize_job_status(job_data.get("status"))
                        self.jobs[job_id] = JobStatus(**job_data)
                log.info(f"加载进度: {len(self.jobs)} 个岗位")
            except Exception as e:
                log.warning(f"加载进度失败: {e}")
    
    def save(self):
        """保存进度"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with open(self.tracker_path, 'w', encoding='utf-8') as f:
            json.dump({k: asdict(v) for k, v in self.jobs.items()}, f, ensure_ascii=False, indent=2)
    
    def add_job(self, job: dict):
        """添加岗位"""
        job_id = str(job.get('job_id'))
        if job_id and job_id not in self.jobs:
            self.jobs[job_id] = JobStatus(
                job_id=job_id,
                title=job.get('title', ''),
                company=job.get('company', ''),
                ai_score=float(job.get('ai_score', 0)),
                is_easy_apply=bool(job.get('is_easy_apply', False)),
                url=job.get('url', f"https://www.linkedin.com/jobs/view/{job_id}"),
                job_description=job.get('job_description', '')
            )
            return True
        return False
    
    def update_status(self, job_id: str, status: str, resume_path: str = ""):
        """更新状态"""
        job_id = str(job_id)
        if job_id in self.jobs:
            normalized_status = normalize_job_status(status)
            self.jobs[job_id].status = normalized_status
            if resume_path:
                self.jobs[job_id].resume_path = resume_path
            if normalized_status == STATUS_APPLIED:
                self.jobs[job_id].applied_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.save()
    
    def is_already_processed(self, job_id: str) -> bool:
        """检查是否已处理"""
        job_id = str(job_id)
        return job_id in self.jobs and is_terminal_lifecycle_status(self.jobs[job_id].status)
    
    def get_pending_jobs(self, is_easy_apply: bool = None) -> List[JobStatus]:
        """获取待处理岗位"""
        result = []
        for job in self.jobs.values():
            if is_pending_lifecycle_status(job.status):
                if is_easy_apply is None or job.is_easy_apply == is_easy_apply:
                    result.append(job)
        return sorted(result, key=lambda x: x.ai_score, reverse=True)
    
    def print_status(self):
        """打印状态"""
        total = len(self.jobs)
        if total == 0:
            print("\n没有岗位数据。请先运行 'python run_pipeline.py crawl'")
            return
            
        easy_apply = [j for j in self.jobs.values() if j.is_easy_apply]
        manual = [j for j in self.jobs.values() if not j.is_easy_apply]
        
        easy_applied = len([j for j in easy_apply if normalize_job_status(j.status) == STATUS_APPLIED])
        easy_pending = len([j for j in easy_apply if is_pending_lifecycle_status(j.status)])
        easy_failed = len([j for j in easy_apply if normalize_job_status(j.status) == STATUS_FAILED])
        
        manual_applied = len([j for j in manual if normalize_job_status(j.status) == STATUS_APPLIED])
        manual_pending = len([j for j in manual if is_pending_lifecycle_status(j.status)])
        
        print("\n" + "=" * 60)
        print("📊 申请进度")
        print("=" * 60)
        print(f"总岗位数: {total}")
        print()
        print(f"Easy Apply: {len(easy_apply)}")
        print(f"  ├── ✅ 已申请: {easy_applied}")
        print(f"  ├── ❌ 失败: {easy_failed}")
        print(f"  └── ⏳ 待处理: {easy_pending}")
        print()
        print(f"手动申请: {len(manual)}")
        print(f"  ├── ✅ 已申请: {manual_applied}")
        print(f"  └── ⏳ 待处理: {manual_pending}")
        print()
        
        if manual_pending > 0:
            print("待处理的手动申请:")
            pending_manual = sorted([j for j in manual if is_pending_lifecycle_status(j.status)], 
                                   key=lambda x: x.ai_score, reverse=True)
            for i, job in enumerate(pending_manual[:10], 1):
                print(f"  {i}. [{job.ai_score:.0f}分] {job.company} - {job.title}")
            if len(pending_manual) > 10:
                print(f"  ... 还有 {len(pending_manual) - 10} 个")
        
        print("=" * 60)


# ============================================================
# 输出生成器
# ============================================================
class OutputGenerator:
    """输出文件生成器 - 简化版，所有文件同一层级"""
    
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = Path(output_dir)
        self.today_dir = self.output_dir / datetime.now().strftime("%Y-%m-%d")
        self.easy_apply_dir = self.today_dir / "easy_apply"
        self.manual_dir = self.today_dir / "manual_apply"
        # Standardized artifact names (snake_case, lowercase)
        self.easy_todo_name = "easy_todo.txt"
        self.manual_todo_name = "manual_todo.txt"
    
    def setup_dirs(self):
        """创建目录结构"""
        self.easy_apply_dir.mkdir(parents=True, exist_ok=True)
        self.manual_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"输出目录: {self.today_dir}")
    
    def generate_job_files(
        self,
        job: dict,
        resume_pdf_path: str,
        counter: int,
        resume_name: str = "Candidate_Resume",
        cover_letter_path: Optional[str] = None,
    ) -> str:
        """
        为单个岗位生成文件
        
        命名策略:
        统一前缀: {resume_name}_{Company}_{Title}
        
        - PDF:  {resume_name}_{Company}_{Title}.pdf               (如果重名加编号)
        - Cover: {resume_name}_{Company}_{Title}_{Score}_cover_letter.txt（若提供源文件）
        - URL:  {resume_name}_{Company}_{Title}_{Score}分.url      (保持排序在一起)
        - Info: {resume_name}_{Company}_{Title}_{Score}分_info.txt (保持排序在一起)
        """
        # 清理文件名（移除特殊字符）
        company = self._clean_filename(job.get('company', 'Unknown')[:30])
        title = self._clean_filename(job.get('title', 'Unknown')[:40])
        score = int(job.get('ai_score', 0))
        
        # 统一的基础文件名 (不含扩展名)
        # 例如: Candidate_Resume_Google_AI_Engineer
        base_name = f"{resume_name}_{company}_{title}"
        
        # 选择目录
        target_dir = self.easy_apply_dir if job.get('is_easy_apply') else self.manual_dir
        
        # 1. 复制 PDF 简历
        # 这里的 PDF 文件名也包含公司和职位，方便识别
        pdf_target = target_dir / f"{base_name}.pdf"
        
        # 如果同名PDF已存在，加编号区分
        if pdf_target.exists():
            pdf_target = target_dir / f"{base_name}_{counter:02d}.pdf"
            # 对应的 base_name 也要更新，以便后续文件保持一致
            base_name = pdf_target.stem
            
        if resume_pdf_path and os.path.exists(resume_pdf_path):
            shutil.copy2(resume_pdf_path, pdf_target)
            log.debug(f"  复制简历: {pdf_target.name}")

        suffix = f"_score_{score}"
        if cover_letter_path and os.path.isfile(cover_letter_path):
            cl_target = target_dir / f"{base_name}{suffix}_cover_letter.txt"
            shutil.copy2(cover_letter_path, cl_target)
            log.debug(f"  复制求职信: {cl_target.name}")
        
        # 2. 创建 URL 快捷方式
        linkedin_url = job.get('url', f"https://www.linkedin.com/jobs/view/{job.get('job_id')}")
        external_url = job.get('external_apply_url')
        if job.get('is_easy_apply'):
            # Easy Apply: 直接用 LinkedIn URL
            url_target = target_dir / f"{base_name}{suffix}.url"
            self._create_url_shortcut(url_target, linkedin_url)
        else:
            # 手动申请: 优先使用公司官网链接
            if external_url:
                # 创建公司官网申请链接
                url_target = target_dir / f"{base_name}{suffix}_apply.url"
                self._create_url_shortcut(url_target, external_url)
            else:
                # 没有外部链接，使用 LinkedIn URL
                url_target = target_dir / f"{base_name}{suffix}.url"
                self._create_url_shortcut(url_target, linkedin_url)
        
        # 3. 创建岗位信息文件（始终包含 LinkedIn 原地址）
        info_target = target_dir / f"{base_name}{suffix}_info.txt"
        self._create_info_file(info_target, job)
        
        return str(pdf_target)
    
    def _clean_filename(self, name: str) -> str:
        """清理文件名并统一到 ascii snake_case。"""
        text = unicodedata.normalize("NFKD", str(name or ""))
        text = text.encode("ascii", "ignore").decode("ascii")
        # 非字母数字统一替换为下划线
        text = re.sub(r"[^A-Za-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text)
        text = text.strip("_").lower()
        return text or "unknown"
    
    def _create_url_shortcut(self, path: Path, url: str):
        """创建 Windows URL 快捷方式"""
        content = f"""[InternetShortcut]
URL={url}
"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _create_info_file(self, path: Path, job: dict):
        """创建岗位信息文件（合并job_info和jd）"""
        linkedin_url = job.get('url', f"https://www.linkedin.com/jobs/view/{job.get('job_id')}")
        external_url = job.get('external_apply_url')
        
        # 申请链接部分
        apply_section = f"🔗 LinkedIn 页面:\n{linkedin_url}"
        if external_url:
            apply_section += f"\n\n🌐 公司官网申请:\n{external_url}"
        
        content = f"""{'=' * 60}
岗位信息
{'=' * 60}

📌 职位: {job.get('title', 'Unknown')}
🏢 公司: {job.get('company', 'Unknown')}
📍 地点: {job.get('location', 'Unknown')}
🎯 AI评分: {job.get('ai_score', 0):.0f}分
💼 类型: {'Easy Apply' if job.get('is_easy_apply') else '手动申请'}

{apply_section}

{'=' * 60}
岗位描述 (JD)
{'=' * 60}

{job.get('job_description', '无描述')}

{'=' * 60}
AI 分析
{'=' * 60}

{job.get('ai_reason', '无分析')}
"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _find_pdf_for_info_txt(self, folder: Path, info_path: Path) -> str:
        """根据 *_info.txt 的文件名匹配同目录下对应 PDF（与 generate_job_files 命名规则一致）。"""
        stem = info_path.stem
        if not stem.endswith("_info"):
            return ""
        core = stem[: -len("_info")]
        m = re.match(r"^(.+)_score_\d+$", core)
        if not m:
            return ""
        prefix = m.group(1)
        best: Optional[Path] = None
        best_mtime = -1.0
        for p in folder.glob("*.pdf"):
            if p.stem == prefix or re.match(rf"^{re.escape(prefix)}_\d{{2}}$", p.stem):
                try:
                    mt = p.stat().st_mtime
                except OSError:
                    continue
                if mt >= best_mtime:
                    best_mtime = mt
                    best = p
        return str(best.resolve()) if best else ""

    def _parse_job_info_txt(self, info_path: Path) -> Optional[dict]:
        """从 easy_apply / manual_apply 下的 *_info.txt 解析岗位字段。"""
        try:
            raw = info_path.read_text(encoding="utf-8")
        except OSError:
            return None
        title = ""
        company = ""
        location = ""
        ai_score = 0.0
        url = ""
        ext_url = ""
        m = re.search(r"📌\s*职位[：:]\s*(.+)", raw)
        if m:
            title = m.group(1).strip()
        m = re.search(r"🏢\s*公司[：:]\s*(.+)", raw)
        if m:
            company = m.group(1).strip()
        m = re.search(r"📍\s*地点[：:]\s*(.+)", raw)
        if m:
            location = m.group(1).strip()
        m = re.search(r"🎯\s*AI评分[：:]\s*([\d.]+)", raw)
        if m:
            try:
                ai_score = float(m.group(1))
            except ValueError:
                ai_score = 0.0
        m = re.search(r"🔗\s*LinkedIn\s*页面[：:]\s*\n\s*(https?://\S+)", raw)
        if m:
            url = m.group(1).strip()
        m = re.search(r"🌐\s*公司官网申请[：:]\s*\n\s*(https?://\S+)", raw)
        if m:
            ext_url = m.group(1).strip()
        jd = ""
        if "岗位描述" in raw and "AI 分析" in raw:
            chunk = raw.split("岗位描述", 1)[1]
            jd = chunk.split("AI 分析", 1)[0][-8000:]
        folder = info_path.parent
        resume_path = self._find_pdf_for_info_txt(folder, info_path)
        return {
            "job_id": "",
            "title": title or "Unknown",
            "company": company or "Unknown",
            "location": location,
            "url": url,
            "external_apply_url": ext_url,
            "ai_score": ai_score,
            "job_description": jd,
            "resume_path": resume_path,
        }

    def _collect_visit_list_jobs_from_folder(self, folder: Path) -> List[dict]:
        """扫描子目录内每个岗位产物（*_info.txt），生成与 processed_jobs 结构兼容的 dict 列表。"""
        if not folder.is_dir():
            return []
        rows: List[dict] = []
        for info_path in sorted(folder.glob("*_info.txt")):
            row = self._parse_job_info_txt(info_path)
            if row:
                rows.append(row)
        rows.sort(key=lambda x: float(x.get("ai_score", 0) or 0), reverse=True)
        return rows

    def generate_joblist(
        self,
        jobs: List[dict],
        interrupted: bool = False,
        run_status_override: Optional[str] = None,
        quiet: bool = False,
    ) -> List[Path]:
        """根据 easy_apply / manual_apply 目录内已有岗位产物生成根目录访问列表（easy_todo.txt、manual_todo.txt）。

        列表内容以子目录中每个 *_info.txt 为准，与本轮内存中的 jobs 参数无关，便于包含历史已生成文件或中断后已落盘岗位。
        可在每生成一份简历后调用一次，及时落盘待办列表，避免进程异常退出时丢失记录。
        """
        if run_status_override is not None:
            status_text = run_status_override
        else:
            status_text = "中断" if interrupted else "完成"
        easy_jobs = self._collect_visit_list_jobs_from_folder(self.easy_apply_dir)
        manual_jobs = self._collect_visit_list_jobs_from_folder(self.manual_dir)

        def _build_content(title: str, bucket: List[dict]) -> str:
            def _detect_base_country(job: dict) -> str:
                text = " ".join([
                    str(job.get("location", "")),
                    str(job.get("title", "")),
                    str(job.get("company", "")),
                    str(job.get("job_description", ""))[:800],
                ]).lower()
                swiss_tokens = [
                    "switzerland",
                    "schweiz",
                    "zurich",
                    "zuerich",
                    "zürich",
                    "geneva",
                    "basel",
                    "olten",
                    "bern",
                    "lausanne",
                    "lugano",
                    "winterthur",
                ]
                if any(token in text for token in swiss_tokens):
                    return "switzerland"
                return "germany"

            def _normalize_resume_path(resume_path: str) -> str:
                if not resume_path:
                    return ""
                # 历史兼容：将旧路径 pipeline-orchestrator/out/... 或 .../artifacts/... 归一到根目录 artifacts/...
                legacy_tokens = ["/pipeline-orchestrator/out/", "/pipeline-orchestrator/artifacts/"]
                matched_tail = None
                for token in legacy_tokens:
                    if token in resume_path:
                        matched_tail = resume_path.split(token, 1)[1]
                        break
                if matched_tail is not None:
                    tail = matched_tail
                    normalized = str((self.output_dir / tail).resolve())
                    if Path(normalized).exists():
                        return normalized
                return str(Path(resume_path).resolve())

            content = f"""{title} ({len(bucket)}个)
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
运行状态: {status_text}
{'=' * 70}

"""
            if not bucket:
                return content + "本次无记录。\n"

            for i, job in enumerate(bucket, 1):
                job_title = job.get('title', '')
                company = job.get('company', '')
                job_url = job.get('url') or (
                    f"https://www.linkedin.com/jobs/view/{job['job_id']}"
                    if job.get('job_id') else ""
                )
                resume_path = job.get('resume_path', '')
                resume_abs = _normalize_resume_path(str(resume_path))
                base_country = _detect_base_country(job)
                content += f"{i:03d}. {job_title} @ {company}\n"
                content += f"    Base Country: {base_country}\n"
                content += f"    Job Link: {job_url}\n"
                content += f"    PDF Path: {resume_abs}\n\n"
            return content

        easy_path = self.today_dir / self.easy_todo_name
        manual_path = self.today_dir / self.manual_todo_name

        with open(easy_path, 'w', encoding='utf-8') as f:
            f.write(_build_content("Easy Apply Todo", easy_jobs))
        with open(manual_path, 'w', encoding='utf-8') as f:
            f.write(_build_content("Manual Apply Todo", manual_jobs))

        if not quiet:
            log.info(f"已生成待办清单: {easy_path}")
            log.info(f"已生成待办清单: {manual_path}")
        else:
            log.debug(f"已刷新待办清单: {easy_path.name}, {manual_path.name}")
        return [easy_path, manual_path]


# ============================================================
# 失败日志
# ============================================================
def append_resume_failure_log(job: dict, error_message: str):
    """记录 AI 简历生成失败日志，便于后续定位问题。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / "resume_failures.log"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lines = [
            "=" * 80,
            f"时间: {timestamp}",
            f"job_id: {job.get('job_id', '')}",
            f"公司: {job.get('company', 'Unknown')}",
            f"职位: {job.get('title', 'Unknown')}",
            f"AI评分: {job.get('ai_score', 0)}",
            f"链接: {job.get('url', '')}",
            f"错误: {error_message}",
            "",
        ]
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        log.warning(f"写入 resume_failures.log 失败: {e}")


@dataclass(frozen=True)
class PipelineArtifacts:
    """集中定义主要产物文件，便于说明各文件职责。"""
    job_registry: str = "jobs_progress.json"
    list_cache: str = "jobs_list_cache.json"
    quota_retry_queue: str = "quota_skipped_jobs.json"
    apply_results: str = "apply_results.json"
    token_usage: str = "token_usage.json"
    resume_failure_log: str = "logs/resume_failures.log"


# ============================================================
# 主流程
# ============================================================
class Pipeline:
    """主流程管理"""
    
    def __init__(self, config_path: str = "pipeline_config.yaml"):
        self.config_mgr = ConfigManager(config_path)
        self.config = self.config_mgr.config
        # 统一输出目录到工作区根目录: job-bot/artifacts
        output_dir_path = (self.config_mgr.base_dir.parent / "artifacts").resolve()
        output_dir = str(output_dir_path)
        self.config.setdefault("output", {})["base_dir"] = output_dir
        self.base_dir = output_dir_path
        self.artifacts = PipelineArtifacts()
        self.tracker = ProgressTracker(output_dir)
        self.output_gen = OutputGenerator(output_dir)
        self._last_resume_error_type = None
        self._last_resume_error_message = ""

    def _artifact_path(self, filename: str) -> Path:
        """统一运行产物路径到 output.base_dir。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir / filename

    def _artifact_paths(self) -> Dict[str, Path]:
        """统一暴露关键文件路径，减少文件名散落在各处。"""
        return {
            "job_registry": self._artifact_path(self.artifacts.job_registry),
            "list_cache": self._artifact_path(self.artifacts.list_cache),
            "quota_retry_queue": self._artifact_path(self.artifacts.quota_retry_queue),
            "apply_results": self._artifact_path(self.artifacts.apply_results),
            "token_usage": self._artifact_path(self.artifacts.token_usage),
            "resume_failure_log": self._artifact_path(self.artifacts.resume_failure_log),
        }

    def _effective_min_ai_score(self) -> int:
        """统一获取最低 AI 分：env 优先，其次配置。"""
        env_value = os.environ.get("PIPELINE__FILTER__MIN_AI_SCORE")
        if env_value is not None and str(env_value).strip() != "":
            try:
                return int(float(str(env_value).strip()))
            except Exception:
                pass
        return int(self.config.get('filter', {}).get('min_ai_score', 70))

    def _effective_ai_model(self) -> str:
        """仅使用中转 OpenAI 模型。"""
        ai = self.config.get("ai", {}) or {}
        return str(ai.get("openai_model") or ai.get("gemini_model") or "gemini-2.5-flash")

    def _company_priority_bonus(self, company_name: str) -> int:
        """公司优先级加权：默认小公司优先，大厂降权。"""
        filter_cfg = self.config.get("filter", {}) or {}
        if not bool(filter_cfg.get("prefer_small_companies", True)):
            return 0
        small_company_bonus = int(filter_cfg.get("small_company_bonus", 2))
        large_company_penalty = int(filter_cfg.get("large_company_penalty", -5))

        large_company_keywords = filter_cfg.get("large_company_keywords") or [
            "google", "amazon", "microsoft", "meta", "apple", "netflix",
            "ibm", "oracle", "sap", "siemens", "adobe", "salesforce",
            "deloitte", "accenture", "capgemini", "infosys", "tcs",
            "deutsche bank", "bloomberg", "intel", "nvidia",
        ]
        name = (company_name or "").lower()
        if any(k in name for k in large_company_keywords):
            return large_company_penalty
        return small_company_bonus

    def _job_sort_score(self, job: dict) -> float:
        """综合排序分：AI 分 + 公司规模偏好加权。"""
        base = float(job.get("ai_score", 0) or 0)
        bonus = self._company_priority_bonus(job.get("company", ""))
        return base + bonus

    def _job_dict_to_job_listing(self, d: Dict[str, Any]):
        """将 jobs_progress.json 中的 dict 转为 linkedin_scraper.JobListing（供批量 LLM 评分）。"""
        import linkedin_scraper

        jid = str(d.get("job_id", "") or "")
        url = d.get("url") or ""
        if not url and jid:
            url = f"https://www.linkedin.com/jobs/view/{jid}"
        ey = d.get("experience_years")
        if ey is not None:
            try:
                ey = int(ey)
            except (TypeError, ValueError):
                ey = None
        return linkedin_scraper.JobListing(
            job_id=jid,
            title=str(d.get("title", "") or ""),
            company=str(d.get("company", "") or ""),
            location=str(d.get("location", "") or ""),
            url=url,
            is_easy_apply=bool(d.get("is_easy_apply", False)),
            job_description=str(d.get("job_description", "") or ""),
            experience_required=d.get("experience_required"),
            posted_time=d.get("posted_time"),
            applicants=d.get("applicants"),
            external_apply_url=d.get("external_apply_url"),
            is_english=bool(d.get("is_english", True)),
            experience_years=ey,
            passed_filter=bool(d.get("passed_filter", False)),
            ai_score=float(d.get("ai_score", 0) or 0),
            ai_reason=str(d.get("ai_reason", "") or ""),
            priority_tier=int(d.get("priority_tier", 99) or 99),
            priority_label=str(d.get("priority_label", "") or ""),
        )

    def print_effective_conditions(self):
        """打印当前生效的关键运行条件。"""
        search = self.config.get("search", {}) or {}
        flt = self.config.get("filter", {}) or {}
        adv = self.config.get("advanced", {}) or {}
        ai = self.config.get("ai", {}) or {}
        output = self.config.get("output", {}) or {}
        log.info("-" * 60)
        log.info("运行环境: default")
        log.info(
            f"搜索条件: positions={search.get('positions', [])}, "
            f"locations={search.get('locations', [])}, "
            f"max_pages={search.get('max_pages')}, sort_by={search.get('sort_by')}, "
            f"auto_resume={search.get('auto_resume', True)}, "
            f"time_filter={search.get('time_filter')}"
        )
        log.info(
            f"筛选条件: min_ai_score={self._effective_min_ai_score()}, "
            f"min_exp={flt.get('min_experience_years')}, "
            f"max_exp={flt.get('max_experience_years')}, "
            f"exclude_german={flt.get('exclude_german')}"
        )
        log.info(
            f"AI条件: provider={ai.get('provider')}, "
            f"model={self._effective_ai_model()}, "
            f"enable_pre_filter={ai.get('enable_pre_filter')}, "
            f"enable_ai_pre_filter={ai.get('enable_ai_pre_filter')}, "
            f"use_llm_scoring={ai.get('use_llm_scoring')}"
        )
        log.info(
            f"性能条件: headless={adv.get('headless')}, "
            f"batch_size={adv.get('batch_size')}, llm_delay={adv.get('llm_delay')}"
        )
        log.info(f"输出目录: {output.get('base_dir')} (by_date={output.get('by_date')})")
        log.info("-" * 60)

    def run_rescore_llm(
        self,
        limit: Optional[int] = None,
        quota_skipped: bool = False,
        quota_skipped_file: Optional[str] = None,
    ) -> int:
        """
        对 jobs_progress.json 中「LLM 批量评分失败」的岗位重新调用 AIScorer.score_jobs，并写回文件。

        匹配条件：ai_reason 包含「LLM评分失败」或「未获取到评分」（与 linkedin_scraper.AIScorer.score_jobs_batch 一致）。
        适用于 429、网络超时等导致整批落入默认分的情况。配额恢复后可将 llm_delay 调大再执行。

        如果 quota_skipped=True：会额外限制 job_id 必须出现在 quota_skipped_jobs.json（或 quota_skipped_file 指定文件）中，
        用于只重跑你关心的“失败列表”而非全量重刷。
        """
        import linkedin_scraper

        self.config_mgr.sync_to_projects()
        jobs_file = self._artifact_paths()["job_registry"]
        if not jobs_file.exists():
            log.error("未找到 jobs_progress.json，请先 crawl")
            return 0

        with open(jobs_file, "r", encoding="utf-8") as f:
            all_jobs = json.load(f)
        if not isinstance(all_jobs, list):
            log.error("jobs_progress.json 应为岗位数组")
            return 0

        markers = ("LLM评分失败", "未获取到评分")

        def needs_rescore(j: dict) -> bool:
            r = j.get("ai_reason") or ""
            return any(m in r for m in markers)

        indices = [i for i, j in enumerate(all_jobs) if needs_rescore(j)]
        if quota_skipped:
            quota_file = (
                Path(quota_skipped_file)
                if quota_skipped_file
                else self._artifact_paths()["quota_retry_queue"]
            )
            if not quota_file.exists():
                log.error(f"未找到 quota_skipped_jobs.json: {quota_file}")
                return 0
            with open(quota_file, "r", encoding="utf-8") as f:
                quota_list = json.load(f)
            if not isinstance(quota_list, list):
                log.error("quota_skipped_jobs.json 应为岗位数组")
                return 0
            quota_job_ids = {
                str(item.get("job_id"))
                for item in quota_list
                if item.get("job_id") is not None
            }
            indices = [
                i for i in indices if str(all_jobs[i].get("job_id")) in quota_job_ids
            ]
        if limit is not None:
            if limit <= 0:
                log.warning("rescore-llm：--limit 须为正整数；传 0 或负数将不处理任何记录")
                return 0
            indices = indices[:limit]

        if not indices:
            log.info(
                "没有需要重新 LLM 评分的岗位（ai_reason 不含："
                + " / ".join(markers)
                + "）"
            )
            return 0

        log.info("=" * 60)
        log.info(f"阶段: 重新 LLM 评分（共 {len(indices)} 条，jobs_progress 原位更新）")
        log.info("=" * 60)

        listings = [self._job_dict_to_job_listing(all_jobs[i]) for i in indices]

        ai_cfg = self.config.get("ai", {}) or {}
        adv_cfg = self.config.get("advanced", {}) or {}
        resume_cfg = self.config.get("resume", {}) or {}
        resume_path = resume_cfg.get("base_json", "resume.json")

        scorer = linkedin_scraper.AIScorer(
            resume_path=resume_path,
            gemini_api_key="",
            model=ai_cfg.get("openai_model", "gemini-2.5-flash"),
            provider="gemini_relay",
            openai_api_key=ai_cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"),
            openai_model=ai_cfg.get("openai_model", "gemini-2.5-flash"),
            openai_base_url=normalize_openai_base_url(ai_cfg.get("openai_base_url", "")),
            use_llm=bool(ai_cfg.get("use_llm_scoring", True)),
            batch_size=int(adv_cfg.get("batch_size", 1) or 1),
        )
        delay = float(adv_cfg.get("llm_delay", 1.0) or 1.0)

        scored = scorer.score_jobs(listings, delay=delay)

        for k, listing in enumerate(scored):
            row_idx = indices[k]
            all_jobs[row_idx]["ai_score"] = listing.ai_score
            all_jobs[row_idx]["ai_reason"] = listing.ai_reason
            all_jobs[row_idx]["priority_tier"] = listing.priority_tier
            all_jobs[row_idx]["priority_label"] = listing.priority_label

        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)

        log.info(f"已写回 {jobs_file}，更新 {len(indices)} 条 ai_score / ai_reason / priority_*")
        return len(indices)
    
    def run_crawl(self) -> List[dict]:
        """阶段1: 爬取岗位"""
        log.info("=" * 60)
        log.info("阶段 1: 爬取岗位")
        log.info("=" * 60)
        
        # 同步配置
        self.config_mgr.sync_to_projects()
        
        # 调用 linkedin_scraper
        try:
            # 动态导入，避免启动时就加载
            import linkedin_scraper
            linkedin_scraper.main()
        except Exception as e:
            log.error(f"爬取失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 加载爬取结果
        jobs = self._load_jobs_progress()
        log.info(f"爬取完成: {len(jobs)} 个岗位")
        return jobs
    
    def _load_jobs_progress(self) -> List[dict]:
        """加载 jobs_progress.json 并去重"""
        jobs_file = self._artifact_paths()["job_registry"]
        if jobs_file.exists():
            with open(jobs_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
            
            normalized_jobs = []
            status_changed = False
            schema_changed = False
            for job in jobs:
                normalized = dict(job)
                # 统一状态字段（兼容历史 state/source_status）
                raw_status = job.get('status')
                if not raw_status and job.get('state'):
                    raw_status = job.get('state')
                    schema_changed = True
                canonical_status = normalize_job_status(raw_status)
                if canonical_status != job.get('status'):
                    status_changed = True
                normalized['status'] = canonical_status
                if 'state' in normalized:
                    normalized.pop('state', None)
                    schema_changed = True
                # 主文件最小 schema 兜底
                required_defaults = {
                    "job_id": str(job.get("job_id", "")),
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "url": job.get("url", ""),
                    "is_easy_apply": bool(job.get("is_easy_apply", False)),
                    "status": canonical_status,
                }
                for k, v in required_defaults.items():
                    if k not in normalized:
                        normalized[k] = v
                        schema_changed = True
                normalized_jobs.append(normalized)
            jobs = normalized_jobs
            
            def get_priority(job):
                return (status_sort_priority(job.get('status')), job.get('ai_score', 0))
            
            # 去重：基于 title+company，保留优先级最高的（状态 > 分数）
            seen = {}
            for job in jobs:
                title = job.get('title', '').lower().strip()
                company = job.get('company', '').lower().strip()
                key = f"{title}|||{company}"
                
                if key not in seen or get_priority(job) > get_priority(seen[key]):
                    seen[key] = job
            
            unique_jobs = list(seen.values())
            
            if len(jobs) > len(unique_jobs) or status_changed or schema_changed:
                if len(jobs) > len(unique_jobs):
                    log.info(f"jobs_progress 去重: {len(jobs)} -> {len(unique_jobs)} (移除 {len(jobs) - len(unique_jobs)} 个重复)")
                elif status_changed:
                    log.info("jobs_progress 状态已规范为 canonical 命名")
                elif schema_changed:
                    log.info("jobs_progress 已完成 schema 规范化")
                # 保存去重或规范化后的数据
                with open(jobs_file, 'w', encoding='utf-8') as f:
                    json.dump(unique_jobs, f, ensure_ascii=False, indent=2)
            
            return unique_jobs
        return []
    
    def _load_list_cache(self) -> List[dict]:
        """加载 jobs_list_cache.json 并去重"""
        cache_file = self._artifact_paths()["list_cache"]
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
            
            # 去重：基于 title+company，保留第一个（通常是最新的）
            seen = set()
            unique_jobs = []
            for job in jobs:
                title = job.get('title', '').lower().strip()
                company = job.get('company', '').lower().strip()
                key = f"{title}|||{company}"
                if key not in seen:
                    seen.add(key)
                    unique_jobs.append(job)
            
            if len(jobs) > len(unique_jobs):
                log.info(f"列表缓存去重: {len(jobs)} -> {len(unique_jobs)} (移除 {len(jobs) - len(unique_jobs)} 个重复)")
            
            return unique_jobs
        return []
    
    def run_crawl_detail(self, limit: int = None) -> List[dict]:
        """从列表缓存中筛选并抓取高分岗位详情
        
        Args:
            limit: 限制处理的岗位数量
        """
        log.info("=" * 60)
        log.info("阶段 1.5: 处理列表缓存 (crawl-detail)")
        log.info("=" * 60)
        
        # 加载列表缓存
        list_jobs = self._load_list_cache()
        if not list_jobs:
            log.error("未找到 jobs_list_cache.json，请先运行 crawl (list_only=true)")
            return []
        
        log.info(f"列表缓存: {len(list_jobs)} 个岗位")
        
        # 同步配置
        self.config_mgr.sync_to_projects()
        
        # 加载 scraper 配置
        scraper_config_file = "scraper_config.yaml"
        with open(scraper_config_file, 'r', encoding='utf-8') as f:
            scraper_config = yaml.safe_load(f)
        
        # AI 粗筛选（只用标题和公司）
        use_ai = scraper_config.get('enable_ai_pre_filter', True)
        all_jobs_with_status = []  # 保存所有岗位（包括被过滤的）
        
        if use_ai:
            try:
                import linkedin_scraper
                ai_scorer = linkedin_scraper.AIScorer(
                    resume_path=scraper_config.get('resume_path', 'resume.json'),
                    gemini_api_key='',
                    model=scraper_config.get('openai_model', scraper_config.get('gemini_model', 'gemini-2.5-flash')),
                    provider='gemini_relay',
                    openai_api_key=scraper_config.get('openai_api_key') or os.environ.get('OPENAI_API_KEY'),
                    openai_model=scraper_config.get('openai_model', 'gemini-2.5-flash'),
                    openai_base_url=normalize_openai_base_url(
                        scraper_config.get('openai_base_url') or os.environ.get('OPENAI_BASE_URL', '')
                    ),
                    use_llm=scraper_config.get('use_llm_scoring', True),
                    batch_size=scraper_config.get('batch_size', 25)
                )
                
                log.info(f"开始 AI 粗筛选 {len(list_jobs)} 个岗位...")
                # 使用 return_all=True 获取所有岗位及其过滤状态
                all_jobs_with_status = ai_scorer.ai_pre_filter(list_jobs, return_all=True)
                passed_jobs = [j for j in all_jobs_with_status if j.get('pre_filter_passed', True)]
                filtered_jobs = [j for j in all_jobs_with_status if not j.get('pre_filter_passed', True)]
                log.info(f"AI 粗筛选结果: {len(passed_jobs)} 个通过, {len(filtered_jobs)} 个被过滤")
            except Exception as e:
                log.warning(f"AI 筛选失败: {e}，使用全部列表")
                passed_jobs = list_jobs
                filtered_jobs = []
        else:
            passed_jobs = list_jobs
            filtered_jobs = []
        
        # 限制数量
        if limit and limit > 0:
            passed_jobs = passed_jobs[:limit]
            log.info(f"限制处理数量: {len(passed_jobs)} 个")
        
        if not passed_jobs:
            log.info("没有需要处理的岗位")
            return []
        
        # 抓取详情
        log.info(f"\n开始抓取 {len(passed_jobs)} 个岗位详情...")
        
        try:
            import linkedin_scraper
            
            # 创建 scraper 实例
            linkedin_cfg = self.config_mgr.config.get('linkedin', {})
            scraper = linkedin_scraper.LinkedInScraper(
                username=linkedin_cfg.get('username', ''),
                password=linkedin_cfg.get('password', ''),
                headless=scraper_config.get('headless', False)
            )
            
            scraper.start_browser()
            if not scraper.login():
                log.error("登录失败")
                return []
            
            all_jobs = []
            for idx, job_info in enumerate(passed_jobs, 1):
                try:
                    log.info(f"正在获取详情 ({idx}/{len(passed_jobs)}): {job_info.get('title', '')[:40]}")
                    job = scraper.get_job_details(job_info['job_id'])
                    if job:
                        all_jobs.append(job)
                        # 保存进度
                        scraper._save_progress(all_jobs)
                except Exception as e:
                    log.error(f"抓取失败 {job_info.get('job_id')}: {e}")
                
                import time, random
                time.sleep(random.uniform(2, 4))
            
            scraper.close()
            
            log.info(f"\n详情抓取完成: {len(all_jobs)} 个岗位")
            
            # 把被过滤的岗位也保存到 jobs_progress.json（设置 ai_score=0, ai_reason=过滤原因）
            if filtered_jobs:
                log.info(f"同时保存 {len(filtered_jobs)} 个被AI预过滤的岗位到 jobs_progress.json...")
                # 加载现有的 jobs_progress.json
                progress_file = self._artifact_paths()["job_registry"]
                existing_jobs = []
                if progress_file.exists():
                    with open(progress_file, 'r', encoding='utf-8') as f:
                        existing_jobs = json.load(f)
                
                # 基于 title+company 去重（而不是 job_id）
                def make_key(j):
                    return f"{j.get('title', '').lower().strip()}|||{j.get('company', '').lower().strip()}"
                
                existing_keys = set(make_key(j) for j in existing_jobs)
                
                # 添加被过滤的岗位
                for job_info in filtered_jobs:
                    key = make_key(job_info)
                    if key not in existing_keys:
                        filtered_job_data = {
                            'job_id': job_info.get('job_id'),
                            'title': job_info.get('title', ''),
                            'company': job_info.get('company', ''),
                            'location': job_info.get('location', ''),
                            'url': f"https://www.linkedin.com/jobs/view/{job_info.get('job_id')}",
                            'is_easy_apply': job_info.get('is_easy_apply', False),
                            'job_description': '',  # 没有详情
                            'passed_filter': False,
                            'ai_score': 0.0,
                            'ai_reason': f"[AI预过滤] {job_info.get('pre_filter_reason', '不符合简历背景')}",
                            '_filtered_at': 'pre_filter'
                        }
                        existing_jobs.append(filtered_job_data)
                        existing_keys.add(key)
                
                # 保存更新后的 jobs_progress.json
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_jobs, f, ensure_ascii=False, indent=2)
                log.info(f"jobs_progress.json 已更新: {len(existing_jobs)} 个岗位")
            
            # 清空列表缓存（已处理）
            cache_file = self._artifact_paths()["list_cache"]
            if cache_file.exists():
                # 移除已处理的岗位（包括抓取了详情的和被过滤掉的）
                processed_ids = set(j.job_id for j in all_jobs)
                filtered_ids = set(j.get('job_id') for j in filtered_jobs) if filtered_jobs else set()
                all_processed_ids = processed_ids | filtered_ids
                remaining = [j for j in list_jobs if j.get('job_id') not in all_processed_ids]
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(remaining, f, ensure_ascii=False, indent=2)
                log.info(f"列表缓存剩余: {len(remaining)} 个岗位 (已处理: {len(all_processed_ids)})")
            
            return [linkedin_scraper.asdict(j) for j in all_jobs]
            
        except Exception as e:
            log.error(f"详情抓取失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def run_generate(self, jobs: List[dict] = None, limit: int = None, force: bool = False, min_ai_score: Optional[int] = None) -> List[dict]:
        """阶段2: 生成定制简历
        
        Args:
            jobs: 岗位列表，如果为None则从jobs_progress.json加载
            limit: 限制处理的岗位数量
            force: 是否强制重新处理已处理过的岗位
            min_ai_score: 覆盖 pipeline 配置中的最低 AI 分（例如数据里全是占位分时）
        """
        log.info("=" * 60)
        log.info("阶段 2: 生成定制简历")
        log.info("=" * 60)
        
        # 加载岗位数据
        if jobs is None:
            jobs = self._load_jobs_progress()
            if not jobs:
                log.error("未找到 jobs_progress.json，请先运行 crawl")
                return []
        
        # 定义黑名单公司 (强行过滤，即使之前评分很高)
        # 已清空黑名单：不过滤任何公司
        BLACKLIST_COMPANIES = []
        
        # 筛选 ai_score >= min_ai_score
        min_score = min_ai_score if min_ai_score is not None else self._effective_min_ai_score()
        
        import linkedin_scraper

        exclude_german_jd = bool((self.config.get("filter") or {}).get("exclude_german", True))
        _jd_lang = linkedin_scraper.JobFilter(0, 0, reject_german_jd=False)

        # 过滤逻辑：分数达标 AND 不是黑名单公司 AND（可选）非德语 JD
        filtered_jobs = []
        skipped_german_jd = 0
        for j in jobs:
            company = j.get('company', '')
            # 检查即时黑名单
            is_blacklisted = False
            for black in BLACKLIST_COMPANIES:
                if black.lower() in company.lower():
                    is_blacklisted = True
                    break
            
            if is_blacklisted:
                continue

            if exclude_german_jd and _jd_lang.is_mostly_german_job_text(
                j.get('title', ''), j.get('job_description', '')
            ):
                skipped_german_jd += 1
                continue

            if j.get('ai_score', 0) >= min_score:
                filtered_jobs.append(j)

        if skipped_german_jd:
            log.info(f"排除德语JD岗位: {skipped_german_jd} 个 (filter.exclude_german=true)")
        log.info(f"筛选 ai_score >= {min_score} 且排除黑名单({len(BLACKLIST_COMPANIES)}家): {len(filtered_jobs)}/{len(jobs)} 个岗位")
        
        # 排除已在 jobs_progress.json 中标记为 applied/closed 的岗位
        filtered_jobs = [
            j for j in filtered_jobs
            if normalize_job_status(j.get('status')) not in [STATUS_APPLIED, STATUS_CLOSED]
        ]

        log.info(f"排除已申请/关闭: {len(filtered_jobs)} 个岗位")
        
        # 同公司同职位去重（保留分数最高的）
        seen_title_companies = {}
        deduped_jobs = []
        for job in sorted(filtered_jobs, key=lambda x: self._job_sort_score(x), reverse=True):
            title = job.get('title', '').lower().strip()
            company = job.get('company', '').lower().strip()
            key = f"{title}|||{company}"
            if key not in seen_title_companies:
                seen_title_companies[key] = True
                deduped_jobs.append(job)
        
        if len(filtered_jobs) > len(deduped_jobs):
            log.info(f"去重同公司同职位: {len(filtered_jobs)} -> {len(deduped_jobs)} 个岗位")
        filtered_jobs = deduped_jobs
        
        # 排除已处理的 (除非 force=True)
        if force:
            new_jobs = filtered_jobs
            log.info(f"强制模式: 处理所有 {len(new_jobs)} 个高分岗位")
        else:
            # 排除已处理的终态岗位，以及已生成简历完成的 resume_ready 岗位
            new_jobs = [
                j for j in filtered_jobs 
                if not self.tracker.is_already_processed(j.get('job_id'))
                and normalize_job_status(j.get('status')) != STATUS_RESUME_READY
            ]
            log.info(f"排除已处理/已生成: {len(new_jobs)} 个待处理")
        
        if not new_jobs:
            log.info("没有新岗位需要处理")
            return []
        
        # 按分数排序并限制数量
        new_jobs = sorted(new_jobs, key=lambda x: self._job_sort_score(x), reverse=True)
        if limit and limit > 0:
            new_jobs = new_jobs[:limit]
            log.info(f"限制处理数量: {len(new_jobs)} 个")
        
        # 显示待处理列表
        log.info("\n待处理岗位:")
        for i, job in enumerate(new_jobs, 1):
            log.info(f"  {i}. [{job.get('ai_score', 0):.0f}分] {job.get('company', '')} - {job.get('title', '')}")
        
        # 创建输出目录
        self.output_gen.setup_dirs()
        
        # 获取基础简历路径
        base_resume = self.config.get('resume', {}).get('base_docx', './cv.docx')
        log.info(f"基础简历路径(base_docx): {base_resume}")
        
        # 检查是否存在 PDF 版本
        base_pdf = base_resume.replace('.docx', '.pdf')
        log.info(f"基础简历PDF候选路径: {base_pdf}")
        if not os.path.exists(base_resume):
            log.warning(f"未找到基础简历文件: {base_resume}（将依赖 word_editor 生成或后续回退）")
        if not os.path.exists(base_pdf) and os.path.exists(base_resume):
            log.info("转换基础简历为 PDF...")
            try:
                from docx2pdf import convert
                convert(base_resume, base_pdf)
                log.info(f"已生成: {base_pdf}")
            except Exception as e:
                log.warning(f"PDF 转换失败: {e}（可能是 docx2pdf/Word 环境问题，或文件路径不可用）")
                base_pdf = None
        elif os.path.exists(base_pdf):
            log.info(f"检测到已存在基础 PDF，跳过转换: {base_pdf}")
        
        # 为每个岗位生成简历
        easy_counter = 1
        manual_counter = 1
        processed_jobs = []
        quota_skipped_jobs = []
        
        # 统一从配置读取输出前缀（非功能性变量集中管理）
        profile_cfg = self.config.get('profile', {})
        resume_name = profile_cfg.get('resume_file_prefix', 'Candidate_Resume')
        
        interrupted = False
        run_error = None
        try:
            for job in new_jobs:  # 已按分数排序
                job_id = job.get('job_id')
                title = job.get('title', 'Unknown')
                company = job.get('company', 'Unknown')
                is_easy = job.get('is_easy_apply', False)
                
                log.info(f"处理: [{job.get('ai_score', 0):.0f}分] {company} - {title}")
                
                # 添加到tracker
                self.tracker.add_job(job)
                
                # 生成定制简历
                try:
                    retryable_markers = [
                        "无法解析 AI 响应的 JSON",
                        "JSON 解析失败",
                        "429",
                        "RESOURCE_EXHAUSTED",
                        "timeout",
                        "timed out",
                        "connection",
                    ]
                    max_attempts = 3
                    resume_pdf_path = None
                    last_err: Optional[Exception] = None
                    for attempt in range(1, max_attempts + 1):
                        try:
                            resume_pdf_path, cover_letter_src = self._generate_resume(
                                job, base_resume, base_pdf
                            )
                            break
                        except Exception as gen_err:
                            last_err = gen_err
                            err_text = str(gen_err).lower()
                            retryable = any(marker.lower() in err_text for marker in retryable_markers)
                            if attempt >= max_attempts or not retryable:
                                raise
                            wait_s = attempt * 2
                            log.warning(f"  生成失败，{wait_s}s 后重试({attempt}/{max_attempts}): {gen_err}")
                            time.sleep(wait_s)
                    if resume_pdf_path is None and last_err is not None:
                        raise last_err
                    if self._last_resume_error_type == "quota_exhausted":
                        raise RuntimeError(self._last_resume_error_message or "AI 简历生成失败：配额不足")

                    if resume_pdf_path:
                        # 生成输出文件
                        counter = easy_counter if is_easy else manual_counter
                        output_path = self.output_gen.generate_job_files(
                            job,
                            resume_pdf_path,
                            counter,
                            resume_name,
                            cover_letter_path=cover_letter_src,
                        )
                        
                        if is_easy:
                            easy_counter += 1
                        else:
                            manual_counter += 1
                        
                        self.tracker.update_status(job_id, STATUS_RESUME_READY, output_path)
                        
                        # 同步 resume_path 到 job 字典（用于 jobs_progress.json）
                        job['resume_path'] = output_path
                        job['status'] = STATUS_RESUME_READY
                        self._sync_single_resume_path_to_progress(job)
                        
                        processed_jobs.append(job)
                        log.info(f"  ✓ 已生成")
                        # 每岗落盘后立即刷新当天根目录 easy_todo / manual_todo（基于 *_info.txt），避免进程中途退出无列表
                        self.output_gen.generate_joblist(
                            processed_jobs,
                            interrupted=False,
                            run_status_override="进行中（已写入岗位的 PDF/info）",
                            quiet=True,
                        )
                    else:
                        raise RuntimeError("AI 简历生成失败：未返回可用简历文件路径")
                        
                except Exception as e:
                    log.error(f"  ✗ 处理失败: {e}")
                    append_resume_failure_log(job, str(e))
                    raise
        except Exception as e:
            interrupted = True
            run_error = e
        finally:
            # 根目录 easy_todo.txt / manual_todo.txt（即使中断也执行）
            self.output_gen.generate_joblist(processed_jobs, interrupted=interrupted)
            self.tracker.save()
            
            # 同步简历路径回 jobs_progress.json
            self._sync_resume_paths_to_progress(processed_jobs)

            if quota_skipped_jobs:
                quota_file = self._artifact_paths()["quota_retry_queue"]
                try:
                    existing = []
                    if quota_file.exists():
                        with open(quota_file, 'r', encoding='utf-8') as f:
                            existing = json.load(f) or []
                    existing.extend(quota_skipped_jobs)
                    with open(quota_file, 'w', encoding='utf-8') as f:
                        json.dump(existing, f, ensure_ascii=False, indent=2)
                    log.info(f"已记录配额跳过清单: {quota_file} (+{len(quota_skipped_jobs)} 条)")
                except Exception as e:
                    log.warning(f"写入配额跳过清单失败: {e}")

        if run_error is not None:
            raise run_error
        
        log.info(f"\n简历生成完成: {len(processed_jobs)} 个")
        log.info(f"  - Easy Apply: {easy_counter - 1} 个")
        log.info(f"  - 手动申请: {manual_counter - 1} 个")
        if quota_skipped_jobs:
            log.info(f"  - 配额跳过: {len(quota_skipped_jobs)} 个")
        log.info(f"输出目录: {self.output_gen.today_dir}")
        self.generate_daily_summary()
        
        return processed_jobs
    
    def _sync_resume_paths_to_progress(self, processed_jobs: List[dict]):
        """同步简历路径回 jobs_progress.json"""
        jobs_file = self._artifact_paths()["job_registry"]
        if not jobs_file.exists():
            return
        
        try:
            with open(jobs_file, 'r', encoding='utf-8') as f:
                all_jobs = json.load(f)
            
            # 建立 job_id -> resume_path 的映射
            resume_map = {
                j.get('job_id'): j.get('resume_path') 
                for j in processed_jobs 
                if j.get('resume_path')
            }
            
            # 更新 jobs_progress.json 中的简历路径
            updated = 0
            for job in all_jobs:
                job_id = job.get('job_id')
                if job_id in resume_map:
                    job['resume_path'] = resume_map[job_id]
                    job['status'] = STATUS_RESUME_READY
                    updated += 1
            
            if updated > 0:
                with open(jobs_file, 'w', encoding='utf-8') as f:
                    json.dump(all_jobs, f, ensure_ascii=False, indent=2)
                log.info(f"✓ 已同步 {updated} 个岗位的简历路径到 jobs_progress.json")
        
        except Exception as e:
            log.warning(f"同步简历路径失败: {e}")

    def _sync_single_resume_path_to_progress(self, job: dict):
        """单个岗位成功后立即落盘，确保失败中断后也能精确续跑。"""
        jobs_file = self._artifact_paths()["job_registry"]
        if not jobs_file.exists():
            return

        job_id = job.get('job_id')
        resume_path = job.get('resume_path')
        if not job_id or not resume_path:
            return

        try:
            with open(jobs_file, 'r', encoding='utf-8') as f:
                all_jobs = json.load(f)

            updated = False
            for row in all_jobs:
                if row.get('job_id') == job_id:
                    row['resume_path'] = resume_path
                    row['status'] = STATUS_RESUME_READY
                    updated = True
                    break

            if updated:
                with open(jobs_file, 'w', encoding='utf-8') as f:
                    json.dump(all_jobs, f, ensure_ascii=False, indent=2)
                log.info(f"✓ 已立即同步岗位 {job_id} 的简历路径到 jobs_progress.json")

        except Exception as e:
            log.warning(f"单岗位同步简历路径失败: {e}")
    
    def _generate_resume(self, job: dict, base_resume: str, base_pdf: str = None) -> Tuple[str, Optional[str]]:
        """生成定制简历（及同批求职信文本文件）。
        
        尝试调用 word_editor 生成定制简历。
        若 AI 简历生成失败，则立即抛错，由上层停止整个流程。
        返回 (PDF 或 DOCX 路径, 求职信 .txt 路径或 None)。
        """
        self._last_resume_error_type = None
        self._last_resume_error_message = ""
        
        def sanitize_filename(name: str) -> str:
            """清理文件名，移除非法字符"""
            name = re.sub(r'[<>:"/\\|?*]', '', name)
            name = name.replace(' ', '_')
            return name[:50]
        
        # 尝试调用 word_editor
        try:
            word_editor_path = self.config_mgr.WORD_EDITOR_PATH
            if word_editor_path.exists():
                # 添加到 sys.path
                if str(word_editor_path) not in sys.path:
                    sys.path.insert(0, str(word_editor_path))
                
                from resume_modifier.main import process_resume
                
                ai_cfg = self.config.get('ai', {}) or {}
                provider = "openai"
                openai_api_key = ai_cfg.get('openai_api_key', '') or os.environ.get("OPENAI_API_KEY", "")
                openai_base_url = normalize_openai_base_url(
                    ai_cfg.get('openai_base_url', '')
                    or ai_cfg.get('server_url', '')
                    or os.environ.get("AI_SERVER_URL", "")
                    or os.environ.get("OPENAI_BASE_URL", "")
                )
                openai_model = ai_cfg.get('openai_model', '') or os.environ.get("OPENAI_MODEL", "")
                
                # 生成输出文件名
                company = job.get('company', 'Unknown')
                title = job.get('title', 'Unknown')
                safe_company = sanitize_filename(company.split()[0] if company else "Company")
                safe_title = sanitize_filename(title.split('(')[0].strip())
                profile_cfg = self.config.get('profile', {}) or {}
                output_prefix = profile_cfg.get('resume_output_prefix') or profile_cfg.get('first_name') or "Candidate"
                output_name = f"{output_prefix}_{safe_company}_{safe_title}"
                applicant_name = (
                    str(profile_cfg.get("full_name") or "").strip()
                    or str(profile_cfg.get("first_name") or "").strip()
                    or None
                )
                write_cover_letter = bool(profile_cfg.get("write_cover_letter", True))
                
                # 创建输出目录 (使用今日目录下的resumes子目录)
                resume_output_dir = self.output_gen.today_dir / "resumes"
                resume_output_dir.mkdir(parents=True, exist_ok=True)
                
                # 调用 word_editor 生成定制简历（仅使用中转 OpenAI）
                def _call_word_editor(call_provider: str, call_api_key: str):
                    os.environ["AI_PROVIDER"] = call_provider
                    call_model = openai_model
                    resolved_base_url = openai_base_url
                    key_status = "set" if call_api_key else "missing"
                    log.info(
                        f"word_editor AI请求参数: provider={call_provider}, "
                        f"model={call_model or '(empty)'}, "
                        f"base_url={resolved_base_url or '(default)'}, "
                        f"api_key={key_status}"
                    )
                    if openai_model:
                        os.environ["OPENAI_MODEL"] = str(openai_model)
                    if openai_base_url:
                        os.environ["OPENAI_BASE_URL"] = str(openai_base_url)
                    return process_resume(
                        resume_path=base_resume,
                        job_description=job.get('job_description', ''),
                        output_dir=str(resume_output_dir),
                        output_name=output_name,
                        api_key=call_api_key,
                        provider=call_provider,
                        model=call_model,
                        skip_pdf=False,
                        verbose=False,
                        debug=False,
                        applicant_full_name=applicant_name,
                        write_cover_letter=write_cover_letter,
                    )

                result = _call_word_editor(provider, openai_api_key)
                
                if result.get('success'):
                    # 保存岗位信息
                    self._save_job_info(resume_output_dir, output_name, job)
                    cover_path = result.get("cover_letter_path")
                    if cover_path and not os.path.isfile(cover_path):
                        cover_path = None
                    
                    # 返回 PDF 路径
                    pdf_path = result.get('pdf_path')
                    if pdf_path and os.path.exists(pdf_path):
                        return (pdf_path, cover_path)
                    
                    # 如果没有 PDF，返回 Word 路径
                    word_path = result.get('word_path')
                    if word_path and os.path.exists(word_path):
                        log.warning(f"  word_editor 未返回可用 PDF，回退使用 DOCX: {word_path}")
                        return (word_path, cover_path)
                    err = "word_editor 成功返回，但既没有可用 PDF，也没有可用 DOCX"
                    self._last_resume_error_message = err
                    log.error(f"  {err}")
                    raise RuntimeError(err)
                else:
                    err = str(result.get('error', 'Unknown'))
                    self._last_resume_error_message = err
                    log.error(f"  word_editor 返回失败: {err}")
                    is_quota_error = ("RESOURCE_EXHAUSTED" in err or "429" in err)
                    if is_quota_error:
                        self._last_resume_error_type = "quota_exhausted"
                        self._last_resume_error_message = err
                    raise RuntimeError(f"AI 简历生成失败: {err}")
                    
        except ImportError as e:
            err = f"word_editor 导入失败: {e}"
            self._last_resume_error_message = err
            log.error(err)
            raise RuntimeError(err)
        except Exception as e:
            err = str(e)
            self._last_resume_error_message = err
            log.error(f"  word_editor 处理失败: {err}")
            if "RESOURCE_EXHAUSTED" in err or "429" in err:
                self._last_resume_error_type = "quota_exhausted"
                self._last_resume_error_message = err
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"AI 简历生成失败: {err}")
    
    def _save_job_info(self, output_dir: Path, output_name: str, job: dict):
        """保存岗位信息到TXT文件"""
        txt_path = output_dir / f"{output_name}_info.txt"
        
        content = f"""Job Title: {job.get('title', '')}
Company: {job.get('company', 'Unknown')}
Location: {job.get('location', 'N/A')}
URL: {job.get('url', '')}
AI Score: {job.get('ai_score', 0):.0f}
AI Reason: {job.get('ai_reason', '')}

===== Job Description =====
{job.get('job_description', 'N/A')}
"""
        
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(content)
    
    def _want_easy_apply_browser(self, no_browser_cli: bool) -> bool:
        """是否用 Selenium 在 LinkedIn 上完成真实 Easy Apply（与填表 JSON 配套）。"""
        if no_browser_cli:
            return False
        env_raw = os.environ.get("EASY_APPLY_BROWSER", "").strip().lower()
        if env_raw in ("0", "false", "no", "off"):
            return False
        if env_raw in ("1", "true", "yes", "on"):
            return True
        return bool((self.config.get("advanced") or {}).get("easy_apply_browser", True))

    def _run_easy_apply_browser_session(self, prepared_rows: List[dict]) -> tuple[List[str], bool]:
        """对已生成 easy_apply_answers 的岗位依次打开页面并填表 / 投递。

        返回 (成功的 job_id 列表, 是否应把成功项同步为 jobs_progress 的 applied)。
        仅填表模式（未在 LinkedIn 点提交）第二项为 False，避免误标为已投递。
        """
        if not prepared_rows:
            return [], False
        import linkedin_scraper
        from easy_apply_browser import run_prepared_jobs

        adv = self.config.get("advanced") or {}
        env_fill = os.environ.get("EASY_APPLY_FILL_ONLY", "").strip().lower()
        if env_fill in ("1", "true", "yes", "on"):
            fill_only = True
        elif env_fill in ("0", "false", "no", "off"):
            fill_only = False
        else:
            fill_only = bool(adv.get("easy_apply_fill_only", False))

        default_pause = 60.0 if fill_only else 4.0
        pause_cfg = adv.get("easy_apply_job_pause_s", default_pause)
        try:
            pause_between = float(os.environ.get("EASY_APPLY_JOB_PAUSE", pause_cfg) or pause_cfg)
        except (TypeError, ValueError):
            pause_between = default_pause

        new_tabs = bool(adv.get("easy_apply_new_tab_per_job", True)) if fill_only else bool(
            adv.get("easy_apply_new_tab_per_job", False)
        )

        keep_open = bool(adv.get("easy_apply_keep_browser_open", fill_only))

        linkedin_cfg = self.config.get("linkedin") or {}
        headless = adv.get("headless", False)
        scraper = linkedin_scraper.LinkedInScraper(
            username=linkedin_cfg.get("username", ""),
            password=linkedin_cfg.get("password", ""),
            headless=headless,
        )
        scraper.start_browser()
        if not scraper.login():
            log.error("浏览器登录失败，跳过 Easy Apply 自动化")
            try:
                scraper.close()
            except Exception:
                pass
            return [], False
        try:
            ok_ids = run_prepared_jobs(
                scraper.browser,
                prepared_rows,
                self.base_dir,
                pause_between_jobs_s=pause_between,
                submit_application=not fill_only,
                new_tab_per_job=new_tabs,
            )
            sync_applied = bool(ok_ids) and not fill_only
            if fill_only and ok_ids:
                log.info(
                    "Easy Apply 填表-only：%s 个岗位已停在提交前（未写入 jobs_progress 为 applied）；"
                    "请在各标签页手动提交后自行更新状态。",
                    len(ok_ids),
                )
            return ok_ids, sync_applied
        finally:
            if not keep_open:
                try:
                    scraper.close()
                except Exception:
                    pass
            else:
                log.info(
                    "已按配置保留浏览器窗口（easy_apply_keep_browser_open）；"
                    "请手动提交各标签申请后自行关闭浏览器。"
                )

    def run_apply(
        self,
        max_jobs: int = 10,
        date_str: Optional[str] = None,
        target_job_id: Optional[str] = None,
        easy_todo_path: Optional[str] = None,
        no_browser: bool = False,
    ):
        """阶段3: 自动申请 Easy Apply
        
        先调用 auto-apply-project 生成填表 JSON；若开启 easy_apply_browser，
        再用 Selenium 遍历 easy_todo 对应岗位。advanced.easy_apply_fill_only 为 true 时
        只填表至提交前并保留标签页，不把 jobs_progress 标为 applied。
        """
        log.info("=" * 60)
        log.info("阶段 3: 自动申请 Easy Apply")
        log.info("=" * 60)
        
        # 加载高分岗位
        jobs = self._load_jobs_progress()
        if not jobs:
            log.error("未找到 jobs_progress.json，请先运行 crawl")
            return
        
        # 筛选待投递岗位（仅显示预览）
        min_score = self._effective_min_ai_score()
        import linkedin_scraper

        exclude_german_jd = bool((self.config.get("filter") or {}).get("exclude_german", True))
        _jd_lang = linkedin_scraper.JobFilter(0, 0, reject_german_jd=False)

        pending_jobs = [
            j for j in jobs 
            if j.get('ai_score', 0) >= min_score 
            and j.get('passed_filter', True)
            and j.get('is_easy_apply', False)  # 只投递 Easy Apply 岗位
            and normalize_job_status(j.get('status')) == STATUS_RESUME_READY
            and bool(j.get('resume_path'))
            and (
                not exclude_german_jd
                or not _jd_lang.is_mostly_german_job_text(
                    j.get('title', ''), j.get('job_description', '')
                )
            )
        ]
        
        # 按分数排序
        pending_jobs.sort(key=lambda x: self._job_sort_score(x), reverse=True)
        
        if not pending_jobs:
            log.info("没有待申请的 Easy Apply 高分岗位（将尝试按 easy_todo.txt 执行）")
        
        if pending_jobs:
            log.info(f"待申请 Easy Apply 岗位: {len(pending_jobs)} 个")
            
            # 显示列表
            log.info("\n待申请岗位列表:")
            for i, job in enumerate(pending_jobs[:15], 1):
                log.info(f"  {i}. [{job.get('ai_score', 0):.0f}分] {job.get('company', '')} - {job.get('title', '')[:35]}")
            
            if len(pending_jobs) > 15:
                log.info(f"  ... 还有 {len(pending_jobs) - 15} 个")
        
        # 通过子进程调用 auto-apply-project
        auto_applier_path = self.config_mgr.AUTO_APPLIER_PATH
        apply_entry = auto_applier_path / "auto_apply" / "main.py"
        
        if not apply_entry.exists():
            log.error(f"找不到 auto-apply-project 入口: {apply_entry}")
            return
        
        artifact_paths = self._artifact_paths()
        jobs_progress_file = artifact_paths["job_registry"]
        results_file = artifact_paths["apply_results"]
        if easy_todo_path:
            easy_todo_file = Path(easy_todo_path)
        elif date_str:
            easy_todo_file = self.base_dir / date_str / "easy_todo.txt"
        else:
            easy_todo_file = self.output_gen.today_dir / "easy_todo.txt"
        if not easy_todo_file.exists():
            try:
                candidates = sorted(self.base_dir.glob("*/easy_todo.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            except Exception:
                candidates = []
            if candidates:
                easy_todo_file = candidates[0]
        
        log.info(f"\n调用 auto-apply-project 自动申请...")
        log.info(f"  入口: {apply_entry}")
        log.info(f"  输入: {easy_todo_file}")
        log.info(f"  输出: {results_file}")

        if not easy_todo_file.exists():
            log.error(f"找不到 easy_todo 文件: {easy_todo_file}")
            return
        
        try:
            import subprocess
            
            cmd = [
                sys.executable,
                "-m",
                "auto_apply.main",
                "--data-dir",
                str(self.base_dir),
                "run-easy-todo",
                "--easy-todo",
                str(easy_todo_file),
                "--jobs-progress",
                str(jobs_progress_file),
            ]
            if max_jobs is not None:
                cmd.extend(["--max", str(max_jobs)])
            if target_job_id:
                cmd.extend(["--job-id", str(target_job_id)])
            
            log.info(f"执行命令: {' '.join(cmd)}")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(auto_applier_path)
            process = subprocess.run(
                cmd,
                cwd=str(auto_applier_path),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            output_text = (process.stdout or "").strip()
            if output_text:
                log.info(f"[auto-apply-project] {output_text}")
            if process.returncode != 0:
                raise RuntimeError(process.stderr.strip() or f"子进程退出码 {process.returncode}")

            # auto-apply-project 会写 apply_results.json、auto_applied.json、easy_apply_answers/*.json
            auto_applied: List[dict] = []
            if results_file.exists():
                try:
                    with open(results_file, "r", encoding="utf-8") as f:
                        payload = json.load(f) or {}
                    auto_applied = payload.get("auto_applied", []) if isinstance(payload, dict) else []
                except Exception as e:
                    log.warning(f"读取申请结果失败: {e}")

            want_browser = self._want_easy_apply_browser(no_browser)
            applied_job_ids: List[str] = []
            browser_sync_applied = True

            if want_browser and auto_applied:
                log.info(f"浏览器 Easy Apply 已启用，准备处理 {len(auto_applied)} 个岗位")
                applied_job_ids, browser_sync_applied = self._run_easy_apply_browser_session(
                    auto_applied
                )
            elif auto_applied:
                applied_job_ids = [
                    str(row.get("job_id"))
                    for row in auto_applied
                    if row.get("job_id")
                ]

            if applied_job_ids and browser_sync_applied:
                self._sync_apply_results(
                    [{"job_id": jid, "success": True} for jid in applied_job_ids]
                )
                self._sync_apply_status_to_progress(applied_job_ids)
                log.info(
                    f"\n申请完成：已标记为已投递 {len(applied_job_ids)} 个"
                    f"（本轮准备 {len(auto_applied)} 个）"
                )
                self.generate_daily_summary()
            elif applied_job_ids and not browser_sync_applied:
                log.info(
                    f"\n浏览器填表完成 {len(applied_job_ids)} 个（未自动标为已投递，等待你在各页手动提交）"
                )
                self.generate_daily_summary()
            elif auto_applied and want_browser:
                log.warning(
                    "浏览器投递未成功任何岗位，jobs_progress 未标为 applied；请检查登录、选择器或岗位是否仍开放 Easy Apply"
                )
            elif not auto_applied:
                log.info("本轮 auto_applied 为空，未更新 jobs_progress")
            
        except Exception as e:
            log.error(f"自动申请失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _sync_apply_results(self, results: list):
        """同步申请结果到 tracker"""
        for result in results:
            job_id = result.get('job_id')
            if not job_id:
                continue
            
            if result.get('success'):
                self.tracker.update_status(job_id, STATUS_APPLIED)
            else:
                # 标记失败，可以后续重试
                self.tracker.update_status(job_id, STATUS_FAILED)

    def _sync_apply_status_to_progress(self, applied_job_ids: List[str]):
        """将自动投递成功结果回写到统一 jobs_progress.json（status=applied）。"""
        if not applied_job_ids:
            return
        jobs_file = self._artifact_paths()["job_registry"]
        if not jobs_file.exists():
            return
        try:
            with open(jobs_file, "r", encoding="utf-8") as f:
                jobs = json.load(f) or []
            updated = 0
            applied_set = {str(i) for i in applied_job_ids}
            for row in jobs:
                if str(row.get("job_id")) in applied_set:
                    row["status"] = STATUS_APPLIED
                    updated += 1
            if updated:
                with open(jobs_file, "w", encoding="utf-8") as f:
                    json.dump(jobs, f, ensure_ascii=False, indent=2)
                log.info(f"✓ 已回写 {updated} 个岗位状态到 jobs_progress.json")
        except Exception as e:
            log.warning(f"回写 jobs_progress 申请状态失败: {e}")

    def generate_daily_summary(self):
        """生成当日 summary.json，便于快速复盘。"""
        try:
            jobs = self._load_jobs_progress()
            total = len(jobs)
            discovered = len([j for j in jobs if normalize_job_status(j.get("status")) == STATUS_DISCOVERED])
            resume_ready = len([j for j in jobs if normalize_job_status(j.get("status")) == STATUS_RESUME_READY])
            applied = len([j for j in jobs if normalize_job_status(j.get("status")) == STATUS_APPLIED])
            failed = len([j for j in jobs if normalize_job_status(j.get("status")) == STATUS_FAILED])
            easy_total = len([j for j in jobs if bool(j.get("is_easy_apply"))])
            manual_total = total - easy_total
            summary = {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_jobs": total,
                "easy_jobs": easy_total,
                "manual_jobs": manual_total,
                "status": {
                    "discovered": discovered,
                    "resume_ready": resume_ready,
                    "applied": applied,
                    "failed": failed,
                },
            }
            day_dir = self.output_gen.today_dir
            day_dir.mkdir(parents=True, exist_ok=True)
            out_file = day_dir / "summary.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            log.info(f"已生成日报: {out_file}")
        except Exception as e:
            log.warning(f"生成日报失败: {e}")
    
    def run_status(self):
        """查看状态"""
        self.tracker.print_status()
        usage_file = self._artifact_paths()["token_usage"]
        if usage_file.exists():
            try:
                with open(usage_file, "r", encoding="utf-8") as f:
                    usage = json.load(f)
                print("\n" + "=" * 50)
                print("💰 LLM 累计费用统计（历史累计）")
                print("=" * 50)
                print(f"API调用次数: {int(usage.get('api_calls', 0) or 0):,}")
                print(f"输入 tokens: {int(usage.get('input_tokens', 0) or 0):,}")
                print(f"输出 tokens: {int(usage.get('output_tokens', 0) or 0):,}")
                print(f"总计 tokens: {int(usage.get('total_tokens', 0) or 0):,}")
                cost = float(usage.get('estimated_cost_usd', 0.0) or 0.0)
                print(f"预估费用: ${cost:.4f} USD (约 ¥{cost * 7.2:.2f})")
                if usage.get("updated_at"):
                    print(f"最后更新: {usage.get('updated_at')}")
                print("=" * 50)
            except Exception as e:
                log.warning(f"读取 token_usage.json 失败: {e}")
        token_tracker.print_summary()
    
    def mark_done(self, identifier: str):
        """标记完成"""
        if identifier.lower() == 'all':
            # 标记所有手动申请为完成
            count = 0
            for job in self.tracker.get_pending_jobs(is_easy_apply=False):
                self.tracker.update_status(job.job_id, STATUS_APPLIED)
                count += 1
            log.info(f"已标记 {count} 个手动申请为完成")
        else:
            # 根据编号或job_id标记
            found = False
            for job_id, job in self.tracker.jobs.items():
                # 支持编号匹配 (如 "001")
                if identifier.isdigit():
                    # 从resume_path提取编号
                    if job.resume_path and f"/{identifier}_" in job.resume_path.replace('\\', '/'):
                        self.tracker.update_status(job_id, STATUS_APPLIED)
                        log.info(f"已标记: {job.company} - {job.title}")
                        found = True
                        break
                # 支持关键词匹配
                elif identifier.lower() in job_id.lower() or \
                     identifier.lower() in job.title.lower() or \
                     identifier.lower() in job.company.lower():
                    self.tracker.update_status(job_id, STATUS_APPLIED)
                    log.info(f"已标记: {job.company} - {job.title}")
                    found = True
                    break
            
            if not found:
                log.warning(f"未找到匹配的岗位: {identifier}")
    
    def open_output(self):
        """打开输出文件夹"""
        output_dir = self.output_gen.today_dir
        
        # 如果今天的目录不存在，尝试打开最新的
        if not output_dir.exists():
            output_base = self.output_gen.output_dir
            if output_base.exists():
                subdirs = sorted([d for d in output_base.iterdir() if d.is_dir()], reverse=True)
                if subdirs:
                    output_dir = subdirs[0]
        
        if output_dir.exists():
            if sys.platform == 'win32':
                os.startfile(str(output_dir))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(output_dir)])
            else:
                subprocess.run(['xdg-open', str(output_dir)])
            log.info(f"已打开: {output_dir}")
        else:
            log.warning(f"输出目录不存在，请先运行 generate")
    
    def run_full(self):
        """完整流程"""
        print("\n🚀 LinkedIn 智能求职助手")
        print("=" * 60)
        
        # 阶段1: 爬取
        jobs = self.run_crawl()
        
        if jobs:
            # 阶段2: 生成简历
            processed = self.run_generate(jobs)
            
            if processed:
                # 阶段3: 自动申请
                self.run_apply()
        
        # 打印汇总
        self.run_status()
        
        print("\n✅ 流程完成")
        print(f"📁 输出目录: {self.output_gen.today_dir}")


# ============================================================
# 命令行入口
# ============================================================
def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='LinkedIn 智能求职助手',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_pipeline.py              # 完整流程
  python run_pipeline.py crawl        # 只爬取岗位（正常模式）
  
  # 大量岗位场景（几百页）:
  # 1. 先设置 scraper_config.yaml 中 list_only: true, max_pages 按需（如 50）
  python run_pipeline.py crawl        # 快速收集列表（不进详情页）
  # 2. 多次运行直到列表收集完
  python run_pipeline.py crawl-detail # AI筛选 + 只抓取高分岗位详情
  python run_pipeline.py crawl-detail --limit 20  # 限制只处理20个
  
  python run_pipeline.py generate     # 生成定制简历 (使用 word_editor)
  python run_pipeline.py generate --limit 5   # 只处理前5个高分岗位
  python run_pipeline.py generate --min-score 50   # 覆盖配置的最低分（如评分均为占位值时）
  python run_pipeline.py rescore-llm              # 重新评分：ai_reason 为 LLM评分失败 / 未获取到评分
  python run_pipeline.py rescore-llm --limit 30    # 只重评前 30 条失败记录（防 429）
  python run_pipeline.py rescore-llm --quota-skipped # 只重评 quota_skipped_jobs.json 里的失败岗位（更快）
  python run_pipeline.py apply        # Easy Apply：见 advanced（easy_apply_fill_only 等；可只填表、多标签、手动提交）
  python run_pipeline.py apply --max 10  # 最多申请10个岗位
  python run_pipeline.py apply --no-browser  # 仅生成填表 JSON，不打开浏览器
  python run_pipeline.py apply --date 2026-04-16 --max 5  # 指定日期 easy_todo
  python run_pipeline.py apply --job-id 4371167896 --max 1 # 仅投递单个岗位
  python run_pipeline.py apply --easy-todo /abs/path/easy_todo.txt --max 3
  python run_pipeline.py status       # 查看进度
  python run_pipeline.py done 001     # 标记编号001的手动申请为完成
  python run_pipeline.py done google  # 标记包含"google"的岗位为完成
  python run_pipeline.py done all     # 标记所有手动申请为完成
  python run_pipeline.py open         # 打开输出文件夹
"""
    )
    parser.add_argument('command', nargs='?', default='full',
                       choices=['full', 'crawl', 'crawl-detail', 'generate', 'rescore-llm', 'apply', 'status', 'done', 'open', 'skip'],
                       help='执行的命令')
    parser.add_argument('arg', nargs='?', help='命令参数')
    parser.add_argument('--config', default=str(Path(__file__).parent / 'pipeline_config.yaml'), help='配置文件路径')
    parser.add_argument('--limit', type=int, default=None, help='限制数量 (generate / crawl-detail / rescore-llm)')
    parser.add_argument('--quota-skipped', action='store_true', help='仅重评 quota_skipped_jobs.json 中的岗位（并结合 ai_reason 失败标记）')
    parser.add_argument('--quota-skipped-file', default=None, help='quota_skipped_jobs.json 路径（仅用于 --quota-skipped）')
    parser.add_argument('--max', type=int, default=None, help='最多申请的岗位数量 (用于 apply 命令)')
    parser.add_argument('--date', default=None, help='指定 easy_todo 日期目录，例如 2026-04-16（用于 apply）')
    parser.add_argument('--job-id', default=None, dest='job_id', help='仅投递指定 job_id（用于 apply）')
    parser.add_argument('--easy-todo', default=None, dest='easy_todo', help='直接指定 easy_todo.txt 路径（用于 apply）')
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='apply 阶段不启动浏览器（仅子进程生成 easy_apply_answers JSON）',
    )
    parser.add_argument('--force', action='store_true', help='强制重新处理已处理过的岗位')
    parser.add_argument('--min-score', type=int, default=None, dest='min_score', help='最低 AI 分，覆盖 pipeline_config 中 filter.min_ai_score（仅 generate）')
    
    args = parser.parse_args()
    
    pipeline = Pipeline(args.config)
    pipeline.print_effective_conditions()
    
    try:
        if args.command == 'full':
            pipeline.run_full()
        elif args.command == 'crawl':
            pipeline.run_crawl()
        elif args.command == 'crawl-detail':
            pipeline.run_crawl_detail(limit=args.limit)
        elif args.command == 'generate':
            pipeline.run_generate(limit=args.limit, force=args.force, min_ai_score=args.min_score)
        elif args.command == 'rescore-llm':
            pipeline.run_rescore_llm(
                limit=args.limit,
                quota_skipped=bool(args.quota_skipped),
                quota_skipped_file=args.quota_skipped_file,
            )
        elif args.command == 'apply':
            pipeline.run_apply(
                max_jobs=args.max,
                date_str=args.date,
                target_job_id=args.job_id,
                easy_todo_path=args.easy_todo,
                no_browser=bool(getattr(args, "no_browser", False)),
            )
        elif args.command == 'status':
            pipeline.run_status()
        elif args.command == 'done':
            if args.arg:
                pipeline.mark_done(args.arg)
            else:
                print("用法: python run_pipeline.py done <编号或关键词>")
                print("示例: python run_pipeline.py done 001")
                print("      python run_pipeline.py done google")
                print("      python run_pipeline.py done all")
        elif args.command == 'skip':
            if args.arg:
                pipeline.tracker.update_status(args.arg, STATUS_SKIPPED)
                log.info(f"已跳过: {args.arg}")
            else:
                print("用法: python run_pipeline.py skip <编号或job_id>")
        elif args.command == 'open':
            pipeline.open_output()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
        # 保存进度
        pipeline.tracker.save()
        token_tracker.print_summary()
    except Exception as e:
        log.error(f"发生错误: {e}")
        import traceback
        traceback.print_exc()
        # 保存进度
        pipeline.tracker.save()


if __name__ == '__main__':
    main()
