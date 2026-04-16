#!/usr/bin/env python3
"""
LinkedIn 智能求职助手 - 统一入口
整合三个项目：LinkedIn-Collect, Word Editor, Auto_job_applier_linkedIn

使用方法:
    python run_pipeline.py              # 完整流程
    python run_pipeline.py crawl        # 只爬取岗位
    python run_pipeline.py generate     # 只生成定制简历
    python run_pipeline.py rescore-llm  # 对 jobs_progress 中 LLM 评分失败的记录重新评分
    python run_pipeline.py apply        # 只自动申请 Easy Apply
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
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional
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

# 文件输出（统一放到 out/logs）
LOG_DIR = Path("out") / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(str(LOG_DIR / f'pipeline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'), encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
log.addHandler(file_handler)


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
        self.config_path = Path(config_path)
        self.base_dir = Path(__file__).parent
        
        # 项目路径
        self.LINKEDIN_COLLECT_PATH = self.base_dir
        # 指向 Word Editor 根目录（兼容目录名可能带 "-main"）
        parent_dir = self.base_dir.parent
        candidate_word_editor_paths = [
            parent_dir / "resume_AI_editor" / "Word Editor",
            parent_dir / "resume_AI_editor-main" / "Word Editor",
        ]
        self.WORD_EDITOR_PATH = next(
            (p for p in candidate_word_editor_paths if p.exists()),
            candidate_word_editor_paths[0],
        )
        self.AUTO_APPLIER_PATH = self.base_dir.parent / "Auto_job_applier_linkedIn"
        
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
        """加载本地环境变量文件（仅 .env）。"""
        env_files = [self.base_dir / ".env"]

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
        scraper_config["output_passed_csv"] = str(Path(output_base) / "jobs_passed.csv")
        scraper_config["output_filtered_csv"] = str(Path(output_base) / "jobs_filtered_out.csv")
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

    def _sync_legacy_config_yaml_from_effective(self, config: dict):
        """按最终生效配置写入 config.yaml（兼容旧脚本）。"""
        legacy_path = self.LINKEDIN_COLLECT_PATH / "config.yaml"
        legacy_cfg = {}
        if legacy_path.exists():
            with open(legacy_path, "r", encoding="utf-8") as f:
                legacy_cfg = yaml.safe_load(f) or {}

        linkedin_cfg = config.get("linkedin", {}) or {}
        search_cfg = config.get("search", {}) or {}
        advanced_cfg = config.get("advanced", {}) or {}
        ai_cfg = config.get("ai", {}) or {}

        legacy_cfg["username"] = linkedin_cfg.get("username", "")
        legacy_cfg["password"] = linkedin_cfg.get("password", "")
        legacy_cfg["phone_number"] = linkedin_cfg.get("phone_number", "")
        legacy_cfg["positions"] = search_cfg.get("positions") or []
        legacy_cfg["locations"] = search_cfg.get("locations") or []
        legacy_cfg["geo_id"] = search_cfg.get("geo_id") or None
        legacy_cfg["time_filter"] = search_cfg.get("time_filter", "")
        legacy_cfg["sort_by"] = search_cfg.get("sort_by", "DD")
        legacy_cfg["max_pages"] = search_cfg.get("max_pages", 1)
        legacy_cfg["experience_level"] = search_cfg.get("experience_level") or []
        legacy_cfg["headless"] = bool(advanced_cfg.get("headless", False))
        legacy_cfg["batch_size"] = advanced_cfg.get("batch_size", 25)
        legacy_cfg["llm_delay"] = advanced_cfg.get("llm_delay", 1.0)
        legacy_cfg["gemini_api_key"] = ""
        legacy_cfg["gemini_model"] = ai_cfg.get("openai_model", "gemini-2.5-flash")
        legacy_cfg["use_llm_scoring"] = bool(ai_cfg.get("use_llm_scoring", True))

        with open(legacy_path, "w", encoding="utf-8") as f:
            yaml.dump(legacy_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
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
                'base_dir': './output'
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
        
        # 2. 同步到 Word Editor
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
        scraper_config['output_passed_csv'] = str(Path(output_base) / 'jobs_passed.csv')
        scraper_config['output_filtered_csv'] = str(Path(output_base) / 'jobs_filtered_out.csv')
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
        """同步到 Word Editor 的 .env"""
        if not self.WORD_EDITOR_PATH.exists():
            log.warning(f"Word Editor 项目不存在: {self.WORD_EDITOR_PATH}")
            return
        
        # 更新 .env 文件 (位于 Word Editor 根目录)
        # 注意: self.WORD_EDITOR_PATH 已修正为指向项目根目录
        env_path = self.WORD_EDITOR_PATH / ".env"
        env_content = f"""# Auto-synced from pipeline_config.yaml
AI_PROVIDER=gemini_relay
OPENAI_API_KEY={self.config.get('ai', {}).get('openai_api_key', '')}
OPENAI_MODEL={self.config.get('ai', {}).get('openai_model', 'gemini-2.5-flash')}
OPENAI_BASE_URL={normalize_openai_base_url(self.config.get('ai', {}).get('openai_base_url') or self.config.get('ai', {}).get('server_url', ''))}
AI_SERVER_URL={normalize_openai_base_url(self.config.get('ai', {}).get('server_url') or self.config.get('ai', {}).get('openai_base_url', ''))}
"""
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        log.debug(f"已更新: {env_path}")
    
    def _sync_auto_applier(self):
        """同步到 Auto_job_applier 的 config/secrets.py"""
        if not self.AUTO_APPLIER_PATH.exists():
            log.warning(f"Auto_job_applier 项目不存在: {self.AUTO_APPLIER_PATH}")
            return
        
        secrets_path = self.AUTO_APPLIER_PATH / "config" / "secrets.py"
        
        if not secrets_path.exists():
            log.warning(f"secrets.py 不存在: {secrets_path}")
            return
        
        try:
            with open(secrets_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 替换 LinkedIn 凭据
            content = re.sub(
                r'username\s*=\s*"[^"]*"',
                f'username = "{self.config.get("linkedin", {}).get("username", "")}"',
                content
            )
            content = re.sub(
                r'password\s*=\s*"[^"]*"',
                f'password = "{self.config.get("linkedin", {}).get("password", "")}"',
                content
            )
            
            # 替换 AI 配置
            api_key = self.config.get('ai', {}).get('openai_api_key', '')
            content = re.sub(
                r'llm_api_key\s*=\s*"[^"]*"',
                f'llm_api_key = "{api_key}"',
                content
            )
            
            with open(secrets_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            log.debug(f"已更新: {secrets_path}")
        except Exception as e:
            log.warning(f"更新 secrets.py 失败: {e}")


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
    status: str = "pending"  # pending, resume_generated, applied, skipped, failed
    resume_path: str = ""
    applied_at: str = ""
    
    
class ProgressTracker:
    """进度追踪器"""
    
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
            self.jobs[job_id].status = status
            if resume_path:
                self.jobs[job_id].resume_path = resume_path
            if status == "applied":
                self.jobs[job_id].applied_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.save()
    
    def is_already_processed(self, job_id: str) -> bool:
        """检查是否已处理"""
        job_id = str(job_id)
        return job_id in self.jobs and self.jobs[job_id].status in ["applied", "skipped"]
    
    def get_pending_jobs(self, is_easy_apply: bool = None) -> List[JobStatus]:
        """获取待处理岗位"""
        result = []
        for job in self.jobs.values():
            if job.status in ["pending", "resume_generated"]:
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
        
        easy_applied = len([j for j in easy_apply if j.status == "applied"])
        easy_pending = len([j for j in easy_apply if j.status in ["pending", "resume_generated"]])
        easy_failed = len([j for j in easy_apply if j.status == "failed"])
        
        manual_applied = len([j for j in manual if j.status == "applied"])
        manual_pending = len([j for j in manual if j.status in ["pending", "resume_generated"]])
        
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
            pending_manual = sorted([j for j in manual if j.status in ["pending", "resume_generated"]], 
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
    
    def setup_dirs(self):
        """创建目录结构"""
        self.easy_apply_dir.mkdir(parents=True, exist_ok=True)
        self.manual_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"输出目录: {self.today_dir}")
    
    def generate_job_files(self, job: dict, resume_pdf_path: str, counter: int, resume_name: str = "Candidate_Resume") -> str:
        """
        为单个岗位生成文件
        
        命名策略:
        统一前缀: {resume_name}_{Company}_{Title}
        
        - PDF:  {resume_name}_{Company}_{Title}.pdf               (如果重名加编号)
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
        
        # 2. 创建 URL 快捷方式
        # 在 base_name 后面加上分数后缀
        suffix = f"_{score}分"
        
        linkedin_url = job.get('url', f"https://www.linkedin.com/jobs/view/{job.get('job_id')}")
        external_url = job.get('external_apply_url')
        
        # 2. 创建 URL 快捷方式
        if job.get('is_easy_apply'):
            # Easy Apply: 直接用 LinkedIn URL
            url_target = target_dir / f"{base_name}{suffix}.url"
            self._create_url_shortcut(url_target, linkedin_url)
        else:
            # 手动申请: 优先使用公司官网链接
            if external_url:
                # 创建公司官网申请链接
                url_target = target_dir / f"{base_name}{suffix}_申请.url"
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
        """清理文件名"""
        # 移除不允许的字符
        invalid_chars = '<>:"/\\|?*\n\r\t'
        for char in invalid_chars:
            name = name.replace(char, '')
        # 移除多余空格
        name = ' '.join(name.split())
        return name.strip()
    
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
    
    def generate_summary(self, jobs: List[dict]):
        """生成汇总文件"""
        easy_apply_jobs = [j for j in jobs if j.get('is_easy_apply')]
        manual_jobs = [j for j in jobs if not j.get('is_easy_apply')]
        
        # 待申请列表（手动）
        if manual_jobs:
            pending_list_path = self.manual_dir / "_待申请列表.txt"
            content = f"""待申请岗位 ({len(manual_jobs)}个)
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 50}

"""
            for i, job in enumerate(sorted(manual_jobs, key=lambda x: x.get('ai_score', 0), reverse=True), 1):
                content += f"□ {i:03d} [{job.get('ai_score', 0):.0f}分] {job.get('company', '')} - {job.get('title', '')}\n"
                linkedin_url = job.get('url') or (
                    f"https://www.linkedin.com/jobs/view/{job['job_id']}"
                    if job.get('job_id') else ""
                )
                if linkedin_url:
                    content += f"    🔗 {linkedin_url}\n"
                ext_url = job.get('external_apply_url')
                if ext_url:
                    content += f"    🌐 官网申请: {ext_url}\n"
            
            content += f"""
{'=' * 50}
使用方法:
1. 点击上方 🔗 链接（或双击同目录 xxx.url）打开申请页面
2. 上传对应的 xxx.pdf 简历
3. 申请完成后可删除该组文件或运行: python run_pipeline.py done 001
"""
            with open(pending_list_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # Easy Apply 列表
        if easy_apply_jobs:
            easy_list_path = self.easy_apply_dir / "_EasyApply列表.txt"
            content = f"""Easy Apply 岗位 ({len(easy_apply_jobs)}个)
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 50}

"""
            for i, job in enumerate(sorted(easy_apply_jobs, key=lambda x: x.get('ai_score', 0), reverse=True), 1):
                content += f"{i:03d} [{job.get('ai_score', 0):.0f}分] {job.get('company', '')} - {job.get('title', '')}\n"
                linkedin_url = job.get('url') or (
                    f"https://www.linkedin.com/jobs/view/{job['job_id']}"
                    if job.get('job_id') else ""
                )
                if linkedin_url:
                    content += f"    🔗 {linkedin_url}\n"
                ext_url = job.get('external_apply_url')
                if ext_url:
                    content += f"    🌐 官网申请: {ext_url}\n"
            
            with open(easy_list_path, 'w', encoding='utf-8') as f:
                f.write(content)


# ============================================================
# 主流程
# ============================================================
class Pipeline:
    """主流程管理"""
    
    def __init__(self, config_path: str = "pipeline_config.yaml"):
        self.config_mgr = ConfigManager(config_path)
        self.config = self.config_mgr.config
        output_dir = self.config.get('output', {}).get('base_dir', './output')
        self.base_dir = Path(output_dir)
        self.tracker = ProgressTracker(output_dir)
        self.output_gen = OutputGenerator(output_dir)
        self._last_resume_error_type = None
        self._last_resume_error_message = ""

    def _artifact_path(self, filename: str) -> Path:
        """统一运行产物路径到 output.base_dir。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir / filename

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
        jobs_file = self._artifact_path("jobs_progress.json")
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
                else self._artifact_path("quota_skipped_jobs.json")
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
        jobs_file = self._artifact_path("jobs_progress.json")
        if jobs_file.exists():
            with open(jobs_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
            
            # 状态优先级：applied > closed > failed > resume_generated > pending
            status_priority = {'applied': 5, 'closed': 4, 'failed': 3, 'resume_generated': 2, 'pending': 1}
            
            def get_priority(job):
                return (status_priority.get(job.get('status', ''), 0), job.get('ai_score', 0))
            
            # 去重：基于 title+company，保留优先级最高的（状态 > 分数）
            seen = {}
            for job in jobs:
                title = job.get('title', '').lower().strip()
                company = job.get('company', '').lower().strip()
                key = f"{title}|||{company}"
                
                if key not in seen or get_priority(job) > get_priority(seen[key]):
                    seen[key] = job
            
            unique_jobs = list(seen.values())
            
            if len(jobs) > len(unique_jobs):
                log.info(f"jobs_progress 去重: {len(jobs)} -> {len(unique_jobs)} (移除 {len(jobs) - len(unique_jobs)} 个重复)")
                # 保存去重后的数据
                with open(jobs_file, 'w', encoding='utf-8') as f:
                    json.dump(unique_jobs, f, ensure_ascii=False, indent=2)
            
            return unique_jobs
        return []
    
    def _load_list_cache(self) -> List[dict]:
        """加载 jobs_list_cache.json 并去重"""
        cache_file = self._artifact_path("jobs_list_cache.json")
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
                progress_file = self._artifact_path("jobs_progress.json")
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
            cache_file = self._artifact_path("jobs_list_cache.json")
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
        filtered_jobs = [j for j in filtered_jobs if j.get('status') not in ['applied', 'closed']]

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
            # 排除已处理的 (applied/skipped) 以及已生成简历的 (resume_generated)
            new_jobs = [
                j for j in filtered_jobs 
                if not self.tracker.is_already_processed(j.get('job_id'))
                and j.get('status') != 'resume_generated'
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
            log.warning(f"未找到基础简历文件: {base_resume}（将依赖 Word Editor 生成或后续回退）")
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
                resume_pdf_path = self._generate_resume(job, base_resume, base_pdf)
                if self._last_resume_error_type == "quota_exhausted":
                    # 配额不足时降级为可追踪的跳过状态，避免重复重试刷日志
                    self.tracker.update_status(job_id, "skipped")
                    job['status'] = 'skipped_quota'
                    job['resume_error'] = self._last_resume_error_message or "Gemini quota exhausted"
                    quota_skipped_jobs.append({
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "ai_score": job.get('ai_score', 0),
                        "reason": job['resume_error'],
                        "skipped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    })
                    log.warning("  ✗ 简历定制失败: AI 配额不足，已标记为 skipped_quota（稍后补额度可重跑）")
                    continue

                if resume_pdf_path:
                    # 生成输出文件
                    counter = easy_counter if is_easy else manual_counter
                    output_path = self.output_gen.generate_job_files(job, resume_pdf_path, counter, resume_name)
                    
                    if is_easy:
                        easy_counter += 1
                    else:
                        manual_counter += 1
                    
                    self.tracker.update_status(job_id, "resume_generated", output_path)
                    
                    # 同步 resume_path 到 job 字典（用于 jobs_progress.json）
                    job['resume_path'] = resume_pdf_path
                    job['status'] = 'resume_generated'
                    
                    processed_jobs.append(job)
                    log.info(f"  ✓ 已生成")
                else:
                    log.warning(f"  ✗ 简历生成失败")
                    
            except Exception as e:
                log.error(f"  ✗ 处理失败: {e}")
        
        # 生成汇总
        self.output_gen.generate_summary(processed_jobs)
        self.tracker.save()
        
        # 同步简历路径回 jobs_progress.json
        self._sync_resume_paths_to_progress(processed_jobs)

        if quota_skipped_jobs:
            quota_file = self._artifact_path("quota_skipped_jobs.json")
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
        
        log.info(f"\n简历生成完成: {len(processed_jobs)} 个")
        log.info(f"  - Easy Apply: {easy_counter - 1} 个")
        log.info(f"  - 手动申请: {manual_counter - 1} 个")
        if quota_skipped_jobs:
            log.info(f"  - 配额跳过: {len(quota_skipped_jobs)} 个")
        log.info(f"输出目录: {self.output_gen.today_dir}")
        
        return processed_jobs
    
    def _sync_resume_paths_to_progress(self, processed_jobs: List[dict]):
        """同步简历路径回 jobs_progress.json"""
        jobs_file = self._artifact_path("jobs_progress.json")
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
                    job['status'] = 'resume_generated'
                    updated += 1
            
            if updated > 0:
                with open(jobs_file, 'w', encoding='utf-8') as f:
                    json.dump(all_jobs, f, ensure_ascii=False, indent=2)
                log.info(f"✓ 已同步 {updated} 个岗位的简历路径到 jobs_progress.json")
        
        except Exception as e:
            log.warning(f"同步简历路径失败: {e}")
    
    def _generate_resume(self, job: dict, base_resume: str, base_pdf: str = None) -> str:
        """生成定制简历
        
        尝试调用 Word Editor，失败则直接使用基础简历
        返回生成的 PDF 路径
        """
        import re
        self._last_resume_error_type = None
        self._last_resume_error_message = ""
        
        def sanitize_filename(name: str) -> str:
            """清理文件名，移除非法字符"""
            name = re.sub(r'[<>:"/\\|?*]', '', name)
            name = name.replace(' ', '_')
            return name[:50]
        
        # 尝试调用 Word Editor
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
                profile_cfg = self.config.get('profile', {})
                output_prefix = profile_cfg.get('resume_output_prefix') or profile_cfg.get('first_name') or "Candidate"
                output_name = f"{output_prefix}_{safe_company}_{safe_title}"
                
                # 创建输出目录 (使用今日目录下的resumes子目录)
                resume_output_dir = self.output_gen.today_dir / "resumes"
                resume_output_dir.mkdir(parents=True, exist_ok=True)
                
                # 调用 Word Editor 生成定制简历（仅使用中转 OpenAI）
                def _call_word_editor(call_provider: str, call_api_key: str):
                    os.environ["AI_PROVIDER"] = call_provider
                    call_model = openai_model
                    resolved_base_url = openai_base_url
                    key_status = "set" if call_api_key else "missing"
                    log.info(
                        f"Word Editor AI请求参数: provider={call_provider}, "
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
                        debug=False
                    )

                result = _call_word_editor(provider, openai_api_key)
                
                if result.get('success'):
                    # 保存岗位信息
                    self._save_job_info(resume_output_dir, output_name, job)
                    
                    # 返回 PDF 路径
                    pdf_path = result.get('pdf_path')
                    if pdf_path and os.path.exists(pdf_path):
                        return pdf_path
                    
                    # 如果没有 PDF，返回 Word 路径
                    word_path = result.get('word_path')
                    if word_path and os.path.exists(word_path):
                        log.warning(f"  Word Editor 未返回可用 PDF，回退使用 DOCX: {word_path}")
                        return word_path
                else:
                    err = str(result.get('error', 'Unknown'))
                    log.warning(f"  Word Editor 返回失败: {err}")
                    is_quota_error = ("RESOURCE_EXHAUSTED" in err or "429" in err)
                    if is_quota_error:
                        self._last_resume_error_type = "quota_exhausted"
                        self._last_resume_error_message = err
                    
        except ImportError as e:
            log.debug(f"Word Editor 导入失败: {e}")
        except Exception as e:
            log.warning(f"  Word Editor 处理失败: {e}")
            err = str(e)
            if "RESOURCE_EXHAUSTED" in err or "429" in err:
                self._last_resume_error_type = "quota_exhausted"
                self._last_resume_error_message = err
            import traceback
            traceback.print_exc()
        
        # 回退：使用基础简历
        if base_pdf and os.path.exists(base_pdf):
            log.info(f"  使用基础 PDF 回退: {base_pdf}")
            return base_pdf
        elif os.path.exists(base_resume) and base_resume.endswith('.pdf'):
            log.info(f"  使用基础简历PDF回退: {base_resume}")
            return base_resume

        log.warning("  无可用简历文件用于回退（既没有定制结果，也没有可用基础PDF）")
        
        return ""
    
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
    
    def run_apply(self, max_jobs: int = 10):
        """阶段3: 自动申请 Easy Apply
        
        调用 Auto_job_applier_linkedIn 项目的 apply_from_progress.py
        通过子进程方式运行，避免跨项目依赖问题
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
            log.info("没有待申请的 Easy Apply 高分岗位")
            return
        
        log.info(f"待申请 Easy Apply 岗位: {len(pending_jobs)} 个")
        
        # 显示列表
        log.info("\n待申请岗位列表:")
        for i, job in enumerate(pending_jobs[:15], 1):
            log.info(f"  {i}. [{job.get('ai_score', 0):.0f}分] {job.get('company', '')} - {job.get('title', '')[:35]}")
        
        if len(pending_jobs) > 15:
            log.info(f"  ... 还有 {len(pending_jobs) - 15} 个")
        
        # 通过子进程调用 Auto_job_applier
        auto_applier_path = self.config_mgr.AUTO_APPLIER_PATH
        apply_script = auto_applier_path / "apply_from_progress.py"
        
        if not apply_script.exists():
            log.error(f"找不到 apply_from_progress.py: {apply_script}")
            return
        
        jobs_progress_file = self.base_dir / "jobs_progress.json"
        results_file = self.base_dir / "apply_results.json"
        
        log.info(f"\n调用 Auto_job_applier 自动申请...")
        log.info(f"  脚本: {apply_script}")
        log.info(f"  输入: {jobs_progress_file}")
        log.info(f"  输出: {results_file}")
        
        try:
            import subprocess
            
            cmd = [
                "python",
                str(apply_script),
                str(jobs_progress_file),
                "--output", str(results_file),
                "--min-score", str(min_score),
                "--max", str(max_jobs)
            ]
            
            log.info(f"执行命令: {' '.join(cmd)}")
            
            # 使用 Popen 以便实时读取输出
            process = subprocess.Popen(
                cmd,
                cwd=str(auto_applier_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # 实时读取输出并解析结果
            apply_results = []
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip()
                if line.startswith("RESULT:"):
                    # 解析实时结果
                    try:
                        import json as json_module
                        result = json_module.loads(line[7:])
                        apply_results.append(result)
                        status = "✅ 成功" if result.get('success') else "❌ 失败"
                        log.info(f"{status} {result.get('company', '')} - {result.get('title', '')[:30]}")
                    except:
                        pass
                elif line:
                    log.info(f"[Auto_job_applier] {line}")
            
            process.wait()
            
            # 同步结果回 tracker
            if apply_results:
                self._sync_apply_results(apply_results)
                log.info(f"\n申请完成，共处理 {len(apply_results)} 个岗位")
                success_count = sum(1 for r in apply_results if r.get('success'))
                log.info(f"  成功: {success_count}, 失败: {len(apply_results) - success_count}")
            
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
                self.tracker.update_status(job_id, 'applied')
            else:
                # 标记失败，可以后续重试
                self.tracker.update_status(job_id, 'failed')
    
    def run_status(self):
        """查看状态"""
        self.tracker.print_status()
        usage_file = self._artifact_path("token_usage.json")
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
                self.tracker.update_status(job.job_id, "applied")
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
                        self.tracker.update_status(job_id, "applied")
                        log.info(f"已标记: {job.company} - {job.title}")
                        found = True
                        break
                # 支持关键词匹配
                elif identifier.lower() in job_id.lower() or \
                     identifier.lower() in job.title.lower() or \
                     identifier.lower() in job.company.lower():
                    self.tracker.update_status(job_id, "applied")
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
  
  python run_pipeline.py generate     # 生成定制简历 (使用 Word Editor)
  python run_pipeline.py generate --limit 5   # 只处理前5个高分岗位
  python run_pipeline.py generate --min-score 50   # 覆盖配置的最低分（如评分均为占位值时）
  python run_pipeline.py rescore-llm              # 重新评分：ai_reason 为 LLM评分失败 / 未获取到评分
  python run_pipeline.py rescore-llm --limit 30    # 只重评前 30 条失败记录（防 429）
  python run_pipeline.py rescore-llm --quota-skipped # 只重评 quota_skipped_jobs.json 里的失败岗位（更快）
  python run_pipeline.py apply        # 只自动申请 Easy Apply
  python run_pipeline.py apply --max 10  # 最多申请10个岗位
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
    parser.add_argument('--config', default='pipeline_config.yaml', help='配置文件路径')
    parser.add_argument('--limit', type=int, default=None, help='限制数量 (generate / crawl-detail / rescore-llm)')
    parser.add_argument('--quota-skipped', action='store_true', help='仅重评 quota_skipped_jobs.json 中的岗位（并结合 ai_reason 失败标记）')
    parser.add_argument('--quota-skipped-file', default=None, help='quota_skipped_jobs.json 路径（仅用于 --quota-skipped）')
    parser.add_argument('--max', type=int, default=None, help='最多申请的岗位数量 (用于 apply 命令)')
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
            pipeline.run_apply(max_jobs=args.max)
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
                pipeline.tracker.update_status(args.arg, "skipped")
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
