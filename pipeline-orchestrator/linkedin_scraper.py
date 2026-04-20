"""
LinkedIn Job Scraper - 岗位爬取、过滤和AI排序系统

功能：
1. 登录LinkedIn
2. 爬取岗位列表（公司、岗位名、JD全文、URL、是否Easy Apply）
3. 过滤规则（英文岗位、经验≤5年）
4. AI排序（基于JD与个人背景匹配度）
"""

from __future__ import annotations

import json
import csv
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import quote_plus
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

import yaml
import pickle
from bs4 import BeautifulSoup
from selenium import webdriver

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service as ChromeService

import webdriver_manager.chrome as ChromeDriverManager
ChromeDriverManager = ChromeDriverManager.ChromeDriverManager

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

def _out_dir() -> Path:
    path = Path(os.environ.get("PIPELINE__OUTPUT__BASE_DIR", "./artifacts"))
    path.mkdir(parents=True, exist_ok=True)
    return path

def _out_file(name: str) -> str:
    return str(_out_dir() / name)


@dataclass
class JobListing:
    """岗位信息数据类"""
    job_id: str
    title: str
    company: str
    location: str
    url: str
    is_easy_apply: bool
    job_description: str
    experience_required: Optional[str] = None
    posted_time: Optional[str] = None
    applicants: Optional[str] = None
    
    # 外部申请链接（非 Easy Apply 时，点击 Apply 跳转的公司官网地址）
    external_apply_url: Optional[str] = None
    
    # 过滤和评分相关
    is_english: bool = True
    experience_years: Optional[int] = None
    passed_filter: bool = False
    ai_score: float = 0.0
    ai_reason: str = ""
    # 投递优先级档位（数字越小越优先；评分后在同级内按 ai_score 排序）
    priority_tier: int = 99
    priority_label: str = ""


class JobDeduplicator:
    """岗位去重器 - 基于(标题, 公司名)去重，并维护历史记录"""
    
    HISTORY_FILE = _out_file("jobs_history.json")
    
    def __init__(self, history_file: str = None):
        self.history_file = history_file or self.HISTORY_FILE
        self.seen_keys = set()
        self.seen_key_dates: Dict[str, str] = {}
        self._load_history()
    
    def _make_key(self, title: str, company: str) -> str:
        """生成去重key"""
        return f"{title.lower().strip()}|||{company.lower().strip()}"
    
    def _load_history(self):
        """加载历史记录"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = self._normalize_history(json.load(f))
                    self.seen_keys = set(history.get("seen_keys", []))
                    raw_dates = history.get("seen_key_dates") or {}
                    self.seen_key_dates = {
                        k: v for k, v in raw_dates.items()
                        if k in self.seen_keys and isinstance(v, str)
                    }
                    log.info(f"已加载历史记录: {len(self.seen_keys)} 个已见岗位")
            except Exception as e:
                log.warning(f"加载历史记录失败: {e}")
                self.seen_keys = set()
                self.seen_key_dates = {}

    def _normalize_history(self, history):
        """兼容历史文件结构：dict（新）或 list（旧清空格式）。"""
        if isinstance(history, dict):
            history.setdefault("jobs", [])
            seen_key_dates = history.setdefault("seen_key_dates", {})
            if not isinstance(seen_key_dates, dict):
                history["seen_key_dates"] = {}
            return history
        if isinstance(history, list):
            # 旧格式可能直接是岗位列表或清空后的 []
            seen_keys = set()
            jobs = []
            for item in history:
                if isinstance(item, dict):
                    jobs.append(item)
                    key = self._make_key(item.get("title", ""), item.get("company", ""))
                    if key != "|||":
                        seen_keys.add(key)
            return {"jobs": jobs, "seen_keys": list(seen_keys), "seen_key_dates": {}}
        return {"jobs": [], "seen_keys": [], "seen_key_dates": {}}
    
    def is_duplicate(self, title: str, company: str) -> bool:
        """检查是否为重复岗位"""
        key = self._make_key(title, company)
        return key in self.seen_keys
    
    def add(self, title: str, company: str):
        """添加岗位到已见列表"""
        key = self._make_key(title, company)
        if key not in self.seen_keys:
            self.seen_key_dates[key] = datetime.now().strftime("%Y-%m-%d")
        self.seen_keys.add(key)
    
    def save_history(self, jobs: List[dict] = None):
        """保存历史记录"""
        try:
            # 加载现有历史
            history = {"jobs": [], "seen_keys": [], "seen_key_dates": {}}
            if os.path.exists(self.history_file):
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = self._normalize_history(json.load(f))
            
            # 更新seen_keys
            self.seen_key_dates = {
                k: v for k, v in self.seen_key_dates.items() if k in self.seen_keys
            }
            history["seen_keys"] = list(self.seen_keys)
            history["seen_key_dates"] = self.seen_key_dates
            history["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 如果提供了jobs，合并进去
            if jobs:
                existing_keys = set(history.get("seen_keys", []))
                for job in jobs:
                    key = self._make_key(job.get('title', ''), job.get('company', ''))
                    if key not in existing_keys:
                        job['added_date'] = datetime.now().strftime("%Y-%m-%d")
                        history["jobs"].append(job)
                        existing_keys.add(key)
            
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            log.info(f"历史记录已保存: {len(self.seen_keys)} 个岗位")
        except Exception as e:
            log.error(f"保存历史记录失败: {e}")
    
    def deduplicate_list(self, jobs: List[dict]) -> List[dict]:
        """对岗位列表去重（返回不重复的岗位）"""
        unique = []
        local_seen = set()
        
        for job in jobs:
            key = self._make_key(job.get('title', ''), job.get('company', ''))
            
            # 检查历史和本次列表
            if key in self.seen_keys:
                log.debug(f"[历史重复] {job.get('title')} @ {job.get('company')}")
                continue
            if key in local_seen:
                log.debug(f"[本次重复] {job.get('title')} @ {job.get('company')}")
                continue
            
            local_seen.add(key)
            unique.append(job)
        
        if len(jobs) > len(unique):
            log.info(f"去重: {len(jobs)} -> {len(unique)} (移除 {len(jobs) - len(unique)} 个重复)")
        
        return unique


class LinkedInScraper:
    """LinkedIn岗位爬取器"""
    
    def __init__(self, username: str, password: str, headless: bool = False, cookies_path: str = "linkedin_cookies.pkl"):
        self.username = username
        self.password = password
        self.headless = headless
        # True 时启用 Chrome detach：Python 进程退出后窗口仍保留（仅 GUI 模式有效）。
        self.detach_on_exit = False
        self.cookies_path = cookies_path
        self.browser = None
        self.wait = None
        self.jobs: List[JobListing] = []
        self.deduplicator = JobDeduplicator()  # 初始化去重器
        # 是否写出 jobs_filtered_out.csv 等岗位 CSV；由 main() 根据 scraper_config.save_csv 设置
        self.write_job_csv: bool = False
    
    def save_cookies(self) -> None:
        """保存cookies到文件"""
        if self.browser:
            cookies = self.browser.get_cookies()
            with open(self.cookies_path, 'wb') as f:
                pickle.dump(cookies, f)
            log.info(f"Cookies已保存到 {self.cookies_path}")
    
    def load_cookies(self) -> bool:
        """从文件加载cookies - 先设置cookie再访问页面，避免闪烁"""
        if not os.path.exists(self.cookies_path):
            log.info("未找到cookie文件，需要手动登录")
            return False
        
        try:
            with open(self.cookies_path, 'rb') as f:
                cookies = pickle.load(f)
            
            log.info(f"正在加载 {len(cookies)} 个cookies...")
            
            # 1. 先访问LinkedIn的任意页面（设置cookie需要先访问域名）
            #    使用一个简单的页面，不会触发登录检查
            self.browser.get("https://www.linkedin.com/uas/login")
            time.sleep(1)  # 短暂等待
            
            # 2. 添加所有cookies
            added_count = 0
            for cookie in cookies:
                try:
                    # 清理cookie，确保格式正确
                    clean_cookie = {
                        'name': cookie['name'],
                        'value': cookie['value'],
                        'domain': cookie.get('domain', '.linkedin.com'),
                        'path': cookie.get('path', '/'),
                    }
                    # 只添加httpOnly和secure如果原cookie有
                    if 'httpOnly' in cookie:
                        clean_cookie['httpOnly'] = cookie['httpOnly']
                    if 'secure' in cookie:
                        clean_cookie['secure'] = cookie['secure']
                    
                    self.browser.add_cookie(clean_cookie)
                    added_count += 1
                except Exception as e:
                    # 浏览器窗口已失效时立即中止，交给上层走账号密码登录
                    if "no such window" in str(e).lower():
                        log.warning("浏览器窗口已关闭，Cookie登录中止，将回退账号密码登录")
                        return False
                    log.debug(f"添加cookie失败 ({cookie.get('name', 'unknown')}): {e}")
            
            log.info(f"已添加 {added_count}/{len(cookies)} 个Cookies")
            
            # 3. 现在直接访问feed页面（不是刷新，而是直接导航）
            #    这样cookie已经设置好了，页面加载时就是登录状态
            self.browser.get("https://www.linkedin.com/feed/")
            time.sleep(random.uniform(2, 3))
            
            return True
        except Exception as e:
            log.warning(f"加载Cookies失败: {e}")
            return False
        
        # 定位器
        self.locators = {
            "search_results": (By.CLASS_NAME, "jobs-search-results-list"),
            "job_cards": (By.XPATH, '//div[@data-job-id]'),
            "job_title": (By.CSS_SELECTOR, "h1.t-24.t-bold.inline"),
            "company_name": (By.CSS_SELECTOR, "a.ember-view.t-black.t-normal"),
            "job_location": (By.CSS_SELECTOR, "span.t-black--light.mt2"),
            "easy_apply_button": (By.XPATH, '//button[contains(@class, "jobs-apply-button")]'),
            "job_description": (By.CLASS_NAME, "jobs-description__content"),
            "job_details": (By.CLASS_NAME, "job-details-jobs-unified-top-card__primary-description-container"),
        }
    
    def browser_options(
        self,
        headless_override: Optional[bool] = None,
        profile_suffix: str = "default",
        remote_debugging_port: int = 9222,
        headless_mode: str = "new",
    ) -> Options:
        """配置浏览器选项 - 增强反检测"""
        options = webdriver.ChromeOptions()
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        
        # ========== 反检测配置 ==========
        # 禁用自动化控制特征
        options.add_argument("--disable-blink-features=AutomationControlled")
        # 禁用自动化扩展
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        # 设置正常的User-Agent
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        # 禁用webdriver标志
        options.add_argument("--disable-infobars")
        
        # 防止Chrome崩溃的选项
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        # Improve startup stability in restricted/containerized environments.
        options.add_argument(f"--remote-debugging-port={remote_debugging_port}")
        options.add_argument(f"--user-data-dir=/tmp/chrome-job-bot-profile-{profile_suffix}")
        # 避免固定端口冲突导致窗口异常关闭
        
        effective_headless = self.headless if headless_override is None else headless_override
        if effective_headless:
            if headless_mode == "legacy":
                options.add_argument("--headless")
            else:
                options.add_argument("--headless=new")  # 新版headless更难检测
            options.add_argument("--window-size=1920,1080")
        else:
            options.add_argument("--start-maximized")
            if self.detach_on_exit:
                options.add_experimental_option("detach", True)
        
        return options
    
    def start_browser(self) -> None:
        """启动浏览器 - 带反检测措施"""
        log.info("正在启动浏览器...")
        browser_service: Optional[ChromeService] = None
        system_driver = self._system_chromedriver_path()
        if system_driver:
            self._assert_driver_compatible(system_driver)
            log.info(f"优先使用系统 chromedriver: {system_driver}")
            browser_service = ChromeService(str(system_driver))
        else:
            try:
                # Fallback to online install when system driver is missing.
                browser_service = ChromeService(ChromeDriverManager().install())
                log.info("系统 chromedriver 不可用，已使用在线下载驱动")
            except Exception as online_err:
                local_driver = self._local_chromedriver_path()
                if not local_driver:
                    raise RuntimeError(
                        f"无法下载 chromedriver 且未找到本地驱动。原始错误: {online_err}"
                    ) from online_err
                self._assert_driver_compatible(local_driver)
                log.warning(f"在线获取 chromedriver 失败，回退使用本地驱动: {local_driver}")
                browser_service = ChromeService(str(local_driver))
        startup_attempts = [
            {"name": "normal-default-profile", "headless": self.headless, "profile": "default", "port": 9222, "headless_mode": "new"},
            {"name": "headless-new-fallback", "headless": True, "profile": "headless-new", "port": 9223, "headless_mode": "new"},
            {"name": "headless-legacy-fallback", "headless": True, "profile": "headless-legacy", "port": 9224, "headless_mode": "legacy"},
            {"name": "clean-profile-legacy-fallback", "headless": True, "profile": f"clean-{int(time.time())}", "port": 9225, "headless_mode": "legacy"},
        ]

        last_error: Optional[Exception] = None
        for attempt in startup_attempts:
            try:
                options = self.browser_options(
                    headless_override=attempt["headless"],
                    profile_suffix=attempt["profile"],
                    remote_debugging_port=attempt["port"],
                    headless_mode=attempt["headless_mode"],
                )
                log.info(
                    f"尝试启动浏览器: {attempt['name']} "
                    f"(headless={attempt['headless']}, mode={attempt['headless_mode']}, port={attempt['port']})"
                )
                self.browser = webdriver.Chrome(service=browser_service, options=options)
                break
            except Exception as startup_err:
                last_error = startup_err
                self._write_browser_startup_log(attempt["name"], startup_err)
                log.warning(f"浏览器启动尝试失败: {attempt['name']} -> {startup_err}")
                try:
                    if self.browser:
                        self.browser.quit()
                except Exception:
                    pass
                self.browser = None

        if not self.browser:
            raise RuntimeError(
                f"浏览器启动失败，已尝试 {len(startup_attempts)} 种模式。最后错误: {last_error}"
            ) from last_error

        self.wait = WebDriverWait(self.browser, 30)
        
        # 执行反检测JavaScript
        self.browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                // 隐藏webdriver属性
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                // 隐藏自动化插件
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                // 隐藏语言
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en', 'de']
                });
            '''
        })
        log.info("浏览器启动成功 (已启用反检测)")

    def _write_browser_startup_log(self, attempt_name: str, error: Exception) -> None:
        """Write browser startup failure details for troubleshooting."""
        try:
            logs_dir = _out_dir() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = logs_dir / f"chrome_startup_{ts}.log"
            content = (
                f"attempt={attempt_name}\n"
                f"timestamp={datetime.now().isoformat()}\n"
                f"headless_config={self.headless}\n"
                f"error_type={type(error).__name__}\n"
                f"error={error}\n"
            )
            log_path.write_text(content, encoding="utf-8")
        except Exception as write_err:
            log.debug(f"写入浏览器启动日志失败: {write_err}")

    def _local_chromedriver_path(self) -> Optional[Path]:
        """Return bundled chromedriver path for current OS."""
        assets_dir = Path(__file__).parent / "assets"
        if sys.platform == "darwin":
            candidate = assets_dir / "chromedriver_darwin"
        elif sys.platform.startswith("linux"):
            candidate = assets_dir / "chromedriver_linux"
        elif sys.platform.startswith("win"):
            candidate = assets_dir / "chromedriver_windows"
        else:
            return None
        if not candidate.exists():
            return None
        try:
            # Ensure executable bit on POSIX to avoid startup failure.
            if os.name != "nt":
                mode = candidate.stat().st_mode
                candidate.chmod(mode | 0o111)
        except Exception:
            pass
        return candidate

    def _system_chromedriver_path(self) -> Optional[Path]:
        """Return chromedriver from PATH if available."""
        system_path = shutil.which("chromedriver")
        if not system_path:
            return None
        candidate = Path(system_path)
        if not candidate.exists():
            return None
        return candidate

    def _assert_driver_compatible(self, driver_path: Path) -> None:
        """Fail fast when local driver major version mismatches Chrome."""
        chrome_major = self._chrome_major_version()
        driver_major = self._driver_major_version(driver_path)
        if chrome_major is None or driver_major is None:
            return
        if chrome_major != driver_major:
            raise RuntimeError(
                "本地 chromedriver 与 Chrome 主版本不兼容："
                f"driver={driver_major}, chrome={chrome_major}。"
                "请升级 chromedriver（建议与 Chrome 主版本一致）或恢复联网下载驱动。"
            )

    def _chrome_major_version(self) -> Optional[int]:
        chrome_bin = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not chrome_bin.exists():
            return None
        try:
            out = subprocess.check_output([str(chrome_bin), "--version"], text=True).strip()
            match = re.search(r"(\d+)\.", out)
            return int(match.group(1)) if match else None
        except Exception:
            return None

    def _driver_major_version(self, driver_path: Path) -> Optional[int]:
        try:
            out = subprocess.check_output([str(driver_path), "--version"], text=True).strip()
            match = re.search(r"ChromeDriver\s+(\d+)\.", out)
            return int(match.group(1)) if match else None
        except Exception:
            return None
    
    def login(self) -> bool:
        """登录LinkedIn（支持Cookie、账号密码或手动登录）"""
        log.info("正在登录LinkedIn...")
        
        # 尝试使用保存的Cookie登录
        if self.load_cookies():
            # Cookie已加载并刷新，直接访问feed页面验证登录状态
            self.browser.get("https://www.linkedin.com/feed/")
            time.sleep(3)  # 等待页面完全加载
            
            # 检查是否已登录（多种方式验证）
            current_url = self.browser.current_url
            page_source = self.browser.page_source
            
            # 检查URL和页面内容
            is_logged_in = (
                ("feed" in current_url or "jobs" in current_url or "mynetwork" in current_url)
                and "login" not in current_url
                and "Sign in" not in page_source[:5000]  # 检查页面开头是否有登录提示
            )
            
            if is_logged_in:
                log.info("✓ Cookie登录成功!")
                return True
            else:
                log.info("Cookie已过期或无效，需要重新登录")
                # 删除过期的cookie文件
                try:
                    os.remove(self.cookies_path)
                    log.info(f"已删除过期的cookie文件: {self.cookies_path}")
                except:
                    pass

        # Cookie加载失败后，先确认窗口仍有效；若无效则自动重启浏览器
        try:
            _ = self.browser.current_url
        except Exception:
            log.warning("浏览器窗口失效，正在重启浏览器并回退账号密码登录")
            try:
                self.browser.quit()
            except Exception:
                pass
            self.start_browser()
        
        # 如果没有配置账号密码，让用户手动登录
        if not self.username or not self.password:
            log.info("未配置账号密码，请在浏览器中手动登录...")
            self.browser.get("https://www.linkedin.com/login")
            input("请在浏览器中完成登录，然后按回车继续...")
            
            # 等待一下确保登录状态同步
            time.sleep(2)
            
            # 检查是否登录成功
            current_url = self.browser.current_url
            if "feed" in current_url or "jobs" in current_url or "mynetwork" in current_url:
                log.info("手动登录成功!")
                self.save_cookies()
                # 验证cookie保存成功
                time.sleep(1)
                return True
            else:
                # 可能用户还在登录页面，再等等
                self.browser.get("https://www.linkedin.com/feed/")
                time.sleep(3)
                if "login" not in self.browser.current_url:
                    log.info("手动登录成功!")
                    self.save_cookies()
                    return True
                log.error("登录失败，请重试")
                return False
        
        # Cookie登录失败，使用账号密码登录
        self.browser.get("https://www.linkedin.com/login?trk=guest_homepage-basic_nav-header-signin")
        
        try:
            # 等待页面加载并定位登录表单元素（LinkedIn 页面结构会变，避免用固定绝对XPath）
            user_field = WebDriverWait(self.browser, 15).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            pw_field = WebDriverWait(self.browser, 15).until(
                EC.presence_of_element_located((By.ID, "password"))
            )
            
            login_button = None
            button_locators = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//form//button[contains(@class,'btn__primary')]"),
                (By.XPATH, "//*[@id='organic-div']//button"),
            ]
            for by, locator in button_locators:
                try:
                    login_button = WebDriverWait(self.browser, 5).until(
                        EC.element_to_be_clickable((by, locator))
                    )
                    if login_button:
                        break
                except Exception:
                    continue
            
            if not login_button:
                raise NoSuchElementException("未找到登录按钮（LinkedIn 登录页结构可能已变化）")
            
            user_field.send_keys(self.username)
            user_field.send_keys(Keys.TAB)
            time.sleep(2)
            
            pw_field.send_keys(self.password)
            time.sleep(2)
            
            login_button.click()
            
            # 等待登录完成（可能需要验证码或2FA）
            log.info("等待登录完成...如果需要验证请在浏览器中手动完成")
            time.sleep(15)
            
            # 检查是否登录成功
            if "feed" in self.browser.current_url or "jobs" in self.browser.current_url:
                log.info("登录成功!")
                self.save_cookies()  # 保存Cookie供下次使用
                return True
            else:
                log.warning("登录可能需要额外验证，请在浏览器中完成...")
                input("完成验证后按回车继续...")
                self.save_cookies()  # 验证完成后保存Cookie
                return True
                
        except TimeoutException:
            log.error("登录超时")
            return False
        except Exception as e:
            log.error(f"登录失败: {e}")
            return False
    
    def search_jobs(self, position: str, location: str, experience_levels: List[int] = None) -> None:
        """搜索岗位
        
        Args:
            position: 职位关键词
            location: 地点
            experience_levels: 经验级别列表 (1=Entry, 2=Associate, 3=Mid-Senior, 4=Director, 5=Executive, 6=Internship)
        """
        log.info(f"搜索岗位: {position} @ {location}")
        
        # 构建搜索URL
        base_url = "https://www.linkedin.com/jobs/search/?"
        params = [
            f"keywords={position}",
            f"location={location}",
            "f_LF=f_AL"  # 只看Easy Apply（可选）
        ]
        
        # 添加经验级别筛选
        if experience_levels:
            exp_str = ",".join(map(str, experience_levels))
            params.append(f"f_E={exp_str}")
        
        url = base_url + "&".join(params)
        self.browser.get(url)
        time.sleep(4)  # 增加等待时间
        
        # 验证是否仍然登录
        if "login" in self.browser.current_url or "authwall" in self.browser.current_url:
            log.warning("跳转搜索页面后登录状态丢失，尝试重新加载...")
            # 刷新页面
            self.browser.refresh()
            time.sleep(3)
            
            # 如果还是未登录，可能需要重新登录
            if "login" in self.browser.current_url or "authwall" in self.browser.current_url:
                log.error("登录状态丢失，请检查cookie或重新登录")
                # 提示用户手动登录
                input("请在浏览器中手动登录，完成后按回车继续...")
                self.save_cookies()
                self.browser.get(url)
                time.sleep(3)
        
        self._scroll_page()
    
    def _scroll_page(self, max_scroll: int = 3000) -> None:
        """滚动页面加载更多内容"""
        for i in range(0, max_scroll, 300):
            self.browser.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.3)
        self.browser.execute_script("window.scrollTo(0, 0);")
    
    def _scroll_job_list(self, max_scrolls: int = 50) -> None:
        """滚动左侧岗位列表到底部，加载所有岗位
        
        Args:
            max_scrolls: 最大滚动次数，防止无限滚动
        """
        try:
            # 新版LinkedIn: 找到真正的滚动容器
            # .scaffold-layout__list > div 是实际可滚动的容器
            scroll_selectors = [
                ".scaffold-layout__list > div",  # 这个是真正的滚动容器
                ".jobs-search-results-list",
                ".scaffold-layout__list-container",
                ".scaffold-layout__list",
            ]
            
            scroll_container = None
            for selector in scroll_selectors:
                try:
                    elem = self.browser.find_element(By.CSS_SELECTOR, selector)
                    # 检查是否是真正的滚动容器
                    scroll_height = self.browser.execute_script("return arguments[0].scrollHeight", elem)
                    client_height = self.browser.execute_script("return arguments[0].clientHeight", elem)
                    
                    if scroll_height > client_height:
                        scroll_container = elem
                        log.info(f"找到滚动容器: {selector} (scrollHeight={scroll_height}, clientHeight={client_height})")
                        break
                except:
                    continue
            
            if scroll_container:
                # 滚动到底部，直到没有新内容加载
                last_height = 0
                no_change_count = 0
                scroll_count = 0
                
                while scroll_count < max_scrolls and no_change_count < 3:
                    # 渐进式滚动：每次滚动一小段，而不是直接到底部
                    current_scroll = self.browser.execute_script("return arguments[0].scrollTop", scroll_container)
                    scroll_height = self.browser.execute_script("return arguments[0].scrollHeight", scroll_container)
                    client_height = self.browser.execute_script("return arguments[0].clientHeight", scroll_container)
                    
                    # 每次滚动一个视口高度的 80%
                    scroll_step = int(client_height * 0.8)
                    new_scroll_top = min(current_scroll + scroll_step, scroll_height)
                    
                    self.browser.execute_script(
                        "arguments[0].scrollTo({top: arguments[1], behavior: 'smooth'})", 
                        scroll_container, new_scroll_top
                    )
                    
                    # 等待加载 - 增加等待时间让懒加载完成
                    time.sleep(2.5)
                    
                    # 获取新的滚动高度
                    new_height = self.browser.execute_script(
                        "return arguments[0].scrollHeight", scroll_container
                    )
                    
                    # 统计当前岗位数量
                    current_jobs = len(self.browser.find_elements(By.CSS_SELECTOR, "div[data-job-id]"))
                    
                    scroll_count += 1
                    log.debug(f"滚动 {scroll_count}: height={new_height}, jobs={current_jobs}")
                    
                    # 检查是否到底部
                    at_bottom = self.browser.execute_script(
                        "return arguments[0].scrollTop + arguments[0].clientHeight >= arguments[0].scrollHeight - 10",
                        scroll_container
                    )
                    
                    # 如果高度没变化且已到底部，计数器+1
                    if new_height == last_height and at_bottom:
                        no_change_count += 1
                        # 尝试微调滚动位置触发加载
                        self.browser.execute_script(
                            "arguments[0].scrollTop = arguments[0].scrollHeight - 100", scroll_container
                        )
                        time.sleep(1.0)
                        self.browser.execute_script(
                            "arguments[0].scrollTop = arguments[0].scrollHeight", scroll_container
                        )
                        time.sleep(1.5)
                    else:
                        no_change_count = 0
                    
                    last_height = new_height
                
                final_jobs = len(self.browser.find_elements(By.CSS_SELECTOR, "div[data-job-id]"))
                log.info(f"列表滚动完成: 滚动{scroll_count}次, 共{final_jobs}个岗位")
                
                # 滚动回顶部
                self.browser.execute_script("arguments[0].scrollTop = 0", scroll_container)
            else:
                # 备用方案：用键盘滚动
                log.warning("未找到滚动容器，尝试用键盘滚动...")
                try:
                    # 点击第一个岗位卡片激活区域
                    first_job = self.browser.find_element(By.CSS_SELECTOR, "div[data-job-id]")
                    first_job.click()
                    time.sleep(0.5)
                    
                    from selenium.webdriver.common.keys import Keys
                    from selenium.webdriver.common.action_chains import ActionChains
                    
                    actions = ActionChains(self.browser)
                    last_count = 0
                    no_change = 0
                    
                    for i in range(max_scrolls):
                        actions.send_keys(Keys.PAGE_DOWN).perform()
                        time.sleep(0.8)
                        
                        current_count = len(self.browser.find_elements(By.CSS_SELECTOR, "div[data-job-id]"))
                        if current_count == last_count:
                            no_change += 1
                            if no_change >= 3:
                                break
                        else:
                            no_change = 0
                        last_count = current_count
                    
                    log.info(f"键盘滚动完成: 共{last_count}个岗位")
                except Exception as e:
                    log.warning(f"键盘滚动失败: {e}")
                
        except Exception as e:
            log.warning(f"滚动岗位列表失败: {e}")
    
    # 德文常见词汇（用于预过滤）
    GERMAN_TITLE_KEYWORDS = [
        'entwickler', 'ingenieur', 'leiter', 'berater', 'spezialist',
        'sachbearbeiter', 'mitarbeiter', 'werkstudent', 'praktikant',
        'fachkraft', 'projektleiter', 'teamleiter', 'abteilungsleiter',
        'geschäftsführer', 'vertrieb', 'buchhaltung', 'verwaltung',
        'kundenberater', 'softwareentwickler', 'systemadministrator',
        '(m/w/d)', '(w/m/d)', '(d/m/w)', 'stellv.', 'stv.'
    ]
    
    # 预过滤排除的标题关键词
    EXCLUDE_TITLE_KEYWORDS = [
        'lead', 'director', 'head of', 'vp ', 'vice president',
        'chief', 'principal', 'staff engineer', 'distinguished'
    ]

    # 职位搜索页「没有任何列表项」时，LinkedIn 在 HTML 里会出现的提示片段（统一小写后做子串匹配）。
    # 用于在仍有 HTTP 200、但继续翻页已无意义时提前结束，见 _page_indicates_no_matching_jobs()。
    # 若界面改版，可用浏览器开发者工具搜页面文案并在此增补。
    LINKEDIN_NO_MATCH_MARKERS: tuple[str, ...] = (
        # English — 主文案 / 筛选项过严时的引导
        "no matching jobs found",
        "no jobs match your filters",
        "try removing some filters",
        # Deutsch — 常见空列表
        "keine passenden jobs",
        "keine jobs gefunden",
        "keine stellen gefunden",
    )
    
    def _should_skip_job(self, title: str, company: str = "") -> tuple[bool, str]:
        """
        预过滤：判断是否应该跳过这个岗位
        
        Returns:
            (是否跳过, 跳过原因)
        """
        title_lower = title.lower()
        
        # 检查是否包含排除关键词（如Lead）
        for keyword in self.EXCLUDE_TITLE_KEYWORDS:
            if keyword in title_lower:
                return True, f"标题含排除词: {keyword}"
        
        # 检查是否是德文标题
        for keyword in self.GERMAN_TITLE_KEYWORDS:
            if keyword in title_lower:
                return True, f"德文标题: {keyword}"
        
        return False, ""
    
    def _page_indicates_no_matching_jobs(self) -> bool:
        """
        判断当前是否为 LinkedIn 的「零结果」搜索页。

        与「本页解析不到职位卡片」(len(jobs_info)==0) 互补：有的版本会先渲染提示文案，
        列表 DOM 尚未出现或结构不同；有的则只有空列表、无独立 banner。两处都判断可减少空跑页数。

        Returns:
            True: 页面源码中含 LINKEDIN_NO_MATCH_MARKERS 之一，应停止当前 keywords+location 的翻页。
            False: 未检测到已知文案，或读取 page_source 失败（保守视为可继续，由后续逻辑判空）。
        """
        try:
            src = (self.browser.page_source or "").lower()
            return any(marker in src for marker in self.LINKEDIN_NO_MATCH_MARKERS)
        except Exception:
            return False
    
    def _extract_visible_jobs(self) -> dict:
        """
        提取当前可见的岗位信息
        优先使用 li[data-occludable-job-id]，因为这些元素不受虚拟滚动影响
        
        Returns:
            {"job_id": {"job_id": "xxx", "title": "xxx", "company": "xxx"}, ...}
        """
        jobs_dict = {}
        
        # 策略1: 使用 li[data-occludable-job-id] - 这些元素不会被虚拟滚动移除！
        try:
            li_cards = self.browser.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id]")
            
            for card in li_cards:
                try:
                    job_id = card.get_attribute("data-occludable-job-id")
                    if not job_id:
                        continue
                    
                    # 从卡片文本提取标题和公司
                    card_text = card.text.strip()
                    if not card_text:  # 可能还没渲染内容
                        # 只记录job_id，后续补充信息
                        if job_id not in jobs_dict:
                            jobs_dict[job_id] = {"job_id": job_id, "title": "", "company": ""}
                        continue
                    
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    
                    title = lines[0] if lines else ""
                    company = lines[1] if len(lines) > 1 else ""
                    
                    if title and len(title) > 3:
                        jobs_dict[job_id] = {"job_id": job_id, "title": title, "company": company}
                    elif job_id not in jobs_dict:
                        jobs_dict[job_id] = {"job_id": job_id, "title": "", "company": ""}
                except:
                    continue
        except:
            pass
        
        # 策略2: 补充使用 div[data-job-id] 获取可见卡片的详细信息
        try:
            div_cards = self.browser.find_elements(By.CSS_SELECTOR, "div[data-job-id]")
            
            for card in div_cards:
                try:
                    job_id = card.get_attribute("data-job-id")
                    if not job_id or job_id == "search":
                        continue
                    
                    card_text = card.text.strip()
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    
                    title = lines[0] if lines else ""
                    company = lines[1] if len(lines) > 1 else ""
                    
                    # 更新或添加岗位信息
                    if title and len(title) > 3:
                        jobs_dict[job_id] = {"job_id": job_id, "title": title, "company": company}
                except:
                    continue
        except:
            pass
        
        return jobs_dict
    
    def get_jobs_from_list_page(self) -> List[dict]:
        """
        从列表页获取岗位基本信息（用于预过滤）
        优化滚动逻辑，确保加载更多岗位
        """
        log.info("正在从列表页提取岗位信息...")
        
        # 尝试找到滚动容器 - 通常是包含 job list 的 div
        # LinkedIn 结构经常变，尝试几种常见的选择器
        scroll_container = None
        try:
            # 常见容器1: .jobs-search-results-list
            scroll_container = self.browser.find_element(By.CSS_SELECTOR, ".jobs-search-results-list")
        except:
            try:
                # 常见容器2: .scaffold-layout__list-container (可能在更外层)
                scroll_container = self.browser.find_element(By.CSS_SELECTOR, ".scaffold-layout__list > div") 
            except:
                pass

        # 如果找不到特定容器，我们尝试通过滚动最后一个可见的 job item 来触发加载
        
        # 先等待初始加载
        time.sleep(2)
        
        # LinkedIn 每页固定约 25 个职位，但只有可视区域内的卡片才会渲染内容
        # 每隔几个卡片滚动一次，让它们都加载出来
        
        job_cards = self.browser.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id]")
        if not job_cards:
            job_cards = self.browser.find_elements(By.CSS_SELECTOR, "div[data-job-id]")
        
        total_cards = len(job_cards)
        log.info(f"页面有 {total_cards} 个卡片元素，开始滚动加载...")
        
        # 每隔 5 个卡片滚动一次，更快但仍能确保内容加载
        step = 5
        for i in range(0, total_cards, step):
            target_idx = min(i + step - 1, total_cards - 1)
            card = job_cards[target_idx]
            try:
                self.browser.execute_script(
                    "arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", 
                    card
                )
                time.sleep(0.8)  # 等待这批卡片渲染
            except Exception as e:
                continue
        
        # 滚动回顶部再滚到底部，确保所有内容都加载
        if job_cards:
            self.browser.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", job_cards[0]
            )
            time.sleep(0.5)
            self.browser.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", job_cards[-1]
            )
            time.sleep(0.5)
                
        # 滚动完成后，统一提取所有信息
        jobs_info = []
        seen_ids = set()
        
        # 重新获取所有元素
        job_cards = self.browser.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id]")
        if not job_cards:
            job_cards = self.browser.find_elements(By.CSS_SELECTOR, "div[data-job-id]")
            
        log.info(f"滚动结束，共找到 {len(job_cards)} 个卡片元素，开始提取信息...")
        
        for card in job_cards:
            try:
                # 优先 data-occludable-job-id
                job_id = card.get_attribute("data-occludable-job-id")
                if not job_id:
                    job_id = card.get_attribute("data-job-id")
                
                if not job_id or job_id == "search" or job_id in seen_ids:
                    continue
                
                seen_ids.add(job_id)
                
                title = ""
                company = ""
                
                # 尝试通过选择器提取标题
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, ".job-card-list__title")
                    title = title_elem.text.strip()
                except:
                    try:
                        title_elem = card.find_element(By.CSS_SELECTOR, "strong")
                        title = title_elem.text.strip()
                    except:
                        pass
                
                # 尝试通过选择器提取公司
                try:
                    company_elem = card.find_element(By.CSS_SELECTOR, ".job-card-container__primary-description")
                    company = company_elem.text.strip()
                except:
                    try:
                        company_elem = card.find_element(By.CSS_SELECTOR, ".artdeco-entity-lockup__subtitle")
                        company = company_elem.text.strip()
                    except:
                        pass
                
                # 如果选择器失败，回退到文本解析
                if not title or not company:
                    lines = [l.strip() for l in card.text.split('\n') if l.strip()]
                    # 过滤掉 "Promoted" 等无关词汇
                    valid_lines = [l for l in lines if l.lower() not in ['promoted', 'easy apply', 'applicants', 'reposted']]
                    
                    if not title:
                        title = valid_lines[0] if valid_lines else ""
                    if not company:
                        company = valid_lines[1] if len(valid_lines) > 1 else ""
                
                # 简单验证
                if title and len(title) > 2:
                    jobs_info.append({
                        "job_id": job_id,
                        "title": title,
                        "company": company
                    })
            except Exception as e:
                continue
                
        log.info(f"列表页提取完成: {len(jobs_info)} 个有效岗位")
        return jobs_info
    
    def get_job_ids_from_page(self, pre_filter: bool = True) -> List[str]:
        """获取当前页面的所有岗位ID（支持预过滤）
        
        Args:
            pre_filter: 是否进行预过滤
        
        Returns:
            通过预过滤的岗位ID列表
        """
        if not pre_filter:
            # 原来的简单方式
            job_ids = []
            self._scroll_job_list()
            time.sleep(1)
            try:
                job_cards = self.browser.find_elements(By.XPATH, '//div[@data-job-id]')
                for card in job_cards:
                    job_id = card.get_attribute("data-job-id")
                    if job_id and job_id != "search":
                        job_ids.append(job_id)
                log.info(f"找到 {len(job_ids)} 个岗位")
            except Exception as e:
                log.error(f"获取岗位ID失败: {e}")
            return list(set(job_ids))
        
        # 带预过滤的方式
        jobs_info = self.get_jobs_from_list_page()
        
        passed_ids = []
        skipped_count = 0
        
        for job in jobs_info:
            should_skip, reason = self._should_skip_job(job["title"], job["company"])
            if should_skip:
                log.info(f"[预过滤跳过] {job['title']} @ {job['company']} | 原因: {reason}")
                skipped_count += 1
            else:
                passed_ids.append(job["job_id"])
        
        log.info(f"列表页预过滤: {len(jobs_info)} 个岗位, 跳过 {skipped_count} 个, 保留 {len(passed_ids)} 个")
        
        return passed_ids
    
    def _save_filtered_jobs(self, jobs: List[dict]):
        """保存被预过滤的岗位，以便记录原因"""
        if not getattr(self, "write_job_csv", False):
            return
        try:
            progress_file = _out_file("jobs_filtered_out.csv")
            file_exists = os.path.exists(progress_file)
            
            with open(progress_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['job_id', 'title', 'company', 'reason', 'timestamp'])
                
                for job in jobs:
                    writer.writerow([
                        job.get('job_id', ''),
                        job.get('title', ''),
                        job.get('company', ''),
                        job.get('pre_filter_reason', 'AI filtered'),
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    ])
            log.info(f"已保存 {len(jobs)} 个被过滤的岗位到 {progress_file}")
        except Exception as e:
            log.warning(f"保存过滤岗位失败: {e}")

    def get_job_details(self, job_id: str) -> Optional[JobListing]:
        """获取单个岗位的详细信息"""
        url = f"https://www.linkedin.com/jobs/view/{job_id}"
        
        try:
            self.browser.get(url)
            time.sleep(4)  # 增加等待时间到4秒
            
            # 等待页面主体加载完成
            try:
                WebDriverWait(self.browser, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "main"))
                )
            except:
                log.warning(f"岗位 {job_id} 页面加载超时")
            
            # 使用多个选择器尝试获取岗位标题
            title = self._get_job_title() or "Unknown Title"
            
            # 使用多个选择器尝试获取公司名称
            company = self._get_company_name() or "Unknown Company"
            
            # 获取地点
            location = self._get_job_location() or ""
            
            # 检查是否有Easy Apply按钮
            is_easy_apply = self._check_easy_apply()
            
            # 获取JD全文
            job_description = self._get_job_description()
            log.debug(f"JD长度: {len(job_description)} 字符")
            
            # 获取发布时间和申请人数
            posted_time = self._get_posted_time()
            applicants = self._get_applicants_count()
            
            # 如果不是 Easy Apply，尝试获取外部申请链接
            external_apply_url = None
            if not is_easy_apply:
                external_apply_url = self._get_external_apply_url()
                if external_apply_url:
                    log.info(f"  外部申请链接: {external_apply_url[:60]}...")
            
            job = JobListing(
                job_id=job_id,
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                url=url,
                is_easy_apply=is_easy_apply,
                job_description=job_description,
                posted_time=posted_time,
                applicants=applicants,
                external_apply_url=external_apply_url
            )
            
            log.info(f"已获取: {title} @ {company} (Easy Apply: {is_easy_apply})")
            return job
            
        except Exception as e:
            log.error(f"获取岗位 {job_id} 详情失败: {e}")
            # 如果是浏览器会话无效，重新抛出异常以触发保存逻辑
            error_msg = str(e).lower()
            if 'invalid session' in error_msg or 'browser' in error_msg or 'disconnected' in error_msg:
                raise  # 重新抛出，让 scrape_jobs 处理
            return None
    
    def _get_job_title(self) -> str:
        """获取岗位标题，尝试多个选择器"""
        selectors = [
            "h1.t-24.t-bold.inline",
            "h1.job-details-jobs-unified-top-card__job-title",
            "h1.topcard__title",
            "h1.jobs-unified-top-card__job-title",
            "h1[class*='job-title']",
            "h1[class*='t-24']",
            ".job-details-jobs-unified-top-card__job-title",
            "h1"  # 最后尝试获取任意h1
        ]
        
        for selector in selectors:
            try:
                element = self.browser.find_element(By.CSS_SELECTOR, selector)
                text = element.text.strip()
                if text and len(text) > 2 and text != "Unknown Title":
                    return text
            except NoSuchElementException:
                continue
        
        # 尝试从页面标题获取
        try:
            page_title = self.browser.title
            if " | " in page_title:
                return page_title.split(" | ")[0].strip()
        except:
            pass
        
        return ""
    
    def _get_company_name(self) -> str:
        """获取公司名称，尝试多个选择器"""
        selectors = [
            "a.ember-view.t-black.t-normal",
            ".job-details-jobs-unified-top-card__company-name a",
            ".job-details-jobs-unified-top-card__company-name",
            "a.topcard__org-name-link",
            ".jobs-unified-top-card__company-name a",
            "a[data-tracking-control-name*='company']",
            ".company-name",
            "span.jobs-unified-top-card__company-name",
        ]
        
        for selector in selectors:
            try:
                element = self.browser.find_element(By.CSS_SELECTOR, selector)
                text = element.text.strip()
                if text and len(text) > 1:
                    return text
            except NoSuchElementException:
                continue
        
        # 尝试从页面标题获取
        try:
            page_title = self.browser.title
            if " | " in page_title:
                parts = page_title.split(" | ")
                if len(parts) > 1:
                    return parts[1].strip()
        except:
            pass
        
        return ""
    
    def _get_job_location(self) -> str:
        """获取岗位地点"""
        selectors = [
            "span.t-black--light.mt2",
            "span.job-details-jobs-unified-top-card__bullet",
            ".jobs-unified-top-card__bullet",
            "span.topcard__flavor--bullet",
            ".job-details-jobs-unified-top-card__primary-description-container span",
        ]
        
        for selector in selectors:
            try:
                elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    # 地点通常包含城市名或国家名
                    if text and any(keyword in text.lower() for keyword in ['germany', 'berlin', 'munich', 'remote', 'hybrid', 'on-site']):
                        return text
            except:
                continue
        
        return ""
    
    def _safe_get_text(self, by: By, selector: str, default: str = "") -> str:
        """安全获取元素文本"""
        try:
            element = self.browser.find_element(by, selector)
            return element.text.strip()
        except NoSuchElementException:
            return default
    
    def _check_easy_apply(self) -> bool:
        """检查是否有Easy Apply按钮 - 增强版"""
        try:
            # 方法1: 查找 Easy Apply 按钮
            selectors = [
                '//button[contains(@class, "jobs-apply-button")]',
                '//button[contains(text(), "Easy Apply")]',
                '//button[contains(text(), "easy apply")]',
                '//button[contains(@aria-label, "Easy Apply")]',
                '//span[contains(text(), "Easy Apply")]',
                '//*[contains(@class, "jobs-apply-button--top-card")]',
            ]
            
            for xpath in selectors:
                try:
                    elements = self.browser.find_elements(By.XPATH, xpath)
                    for elem in elements:
                        text = elem.text.lower() if elem.text else ""
                        aria = elem.get_attribute("aria-label") or ""
                        if "easy apply" in text or "easy apply" in aria.lower():
                            log.debug(f"Found Easy Apply via: {xpath}")
                            return True
                except:
                    continue
            
            # 方法2: 检查页面源码中是否包含 Easy Apply 关键词
            try:
                page_source = self.browser.page_source
                if 'Easy Apply' in page_source or 'easyApply' in page_source:
                    # 再确认不是"Apply"（外部申请）按钮
                    apply_buttons = self.browser.find_elements(
                        By.XPATH, '//button[contains(@class, "jobs-apply-button")]'
                    )
                    for btn in apply_buttons:
                        btn_text = btn.text or ""
                        if "Easy" in btn_text or "easy" in btn_text:
                            log.debug("Found Easy Apply via page source check")
                            return True
            except:
                pass
            
            return False
        except Exception as e:
            log.debug(f"Easy Apply 检测异常: {e}")
            return False
    
    def _get_external_apply_url(self) -> Optional[str]:
        """
        获取外部申请链接（公司官网）
        
        对于非 Easy Apply 岗位，点击 Apply 按钮会跳转到公司官网。
        这里尝试获取该跳转链接。
        
        Returns:
            外部申请URL，如果无法获取则返回 None
        """
        try:
            # 方法1: 查找 Apply 按钮上的链接
            apply_link_selectors = [
                'a.jobs-apply-button',
                'a[data-tracking-control-name*="apply"]',
                '.jobs-apply-button[href]',
                'a[href*="applyUrl"]',
            ]
            
            for selector in apply_link_selectors:
                try:
                    element = self.browser.find_element(By.CSS_SELECTOR, selector)
                    href = element.get_attribute('href')
                    if href and 'linkedin.com' not in href:
                        return href
                except:
                    continue
            
            # 方法2: 点击 Apply 按钮，观察跳转或新窗口
            try:
                apply_buttons = self.browser.find_elements(
                    By.XPATH, '//button[contains(@class, "jobs-apply-button")] | //a[contains(@class, "jobs-apply-button")]'
                )
                
                for btn in apply_buttons:
                    btn_text = (btn.text or "").lower()
                    # 排除 Easy Apply 按钮
                    if "easy" in btn_text:
                        continue
                    
                    # 检查是否是链接按钮
                    href = btn.get_attribute('href')
                    if href:
                        # 解析跳转链接
                        if 'linkedin.com/redir' in href or 'applyUrl' in href:
                            # LinkedIn 的重定向链接，尝试解析目标URL
                            import urllib.parse
                            parsed = urllib.parse.urlparse(href)
                            params = urllib.parse.parse_qs(parsed.query)
                            if 'url' in params:
                                return urllib.parse.unquote(params['url'][0])
                            if 'applyUrl' in params:
                                return urllib.parse.unquote(params['applyUrl'][0])
                        elif 'linkedin.com' not in href:
                            return href
                    
                    # 方法3: 检查按钮的 onclick 或 data 属性
                    onclick = btn.get_attribute('onclick') or ""
                    data_url = btn.get_attribute('data-apply-url') or btn.get_attribute('data-external-apply-url') or ""
                    
                    if data_url and 'linkedin.com' not in data_url:
                        return data_url
            except Exception as e:
                log.debug(f"获取外部链接方法2失败: {e}")
            
            # 方法4: 检查页面中的隐藏元素或 JSON 数据
            try:
                # 有时外部链接存储在页面的 JSON 数据中
                page_source = self.browser.page_source
                import re
                
                # 查找 applyUrl 模式
                patterns = [
                    r'"applyUrl"\s*:\s*"([^"]+)"',
                    r'"externalApplyUrl"\s*:\s*"([^"]+)"',
                    r'"companyApplyUrl"\s*:\s*"([^"]+)"',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, page_source)
                    if match:
                        url = match.group(1)
                        # 解码 Unicode 转义
                        url = url.encode().decode('unicode_escape')
                        if 'linkedin.com' not in url:
                            return url
            except Exception as e:
                log.debug(f"获取外部链接方法4失败: {e}")
            
            return None
            
        except Exception as e:
            log.debug(f"获取外部申请链接失败: {e}")
            return None
    
    def _get_job_description(self) -> str:
        """获取岗位描述全文 - 增强版，尝试多个选择器"""
        
        # 先滚动页面以触发懒加载
        try:
            self.browser.execute_script("window.scrollTo(0, 500);")
            time.sleep(1)
        except:
            pass
        
        # 尝试点击所有可能的"See more"/"Show more"按钮展开全文
        see_more_selectors = [
            # 新版LinkedIn按钮
            "button[aria-label*='more']",
            "button[aria-label*='展开']",
            "button[aria-label*='Show']",
            "button[aria-label*='See']",
            # 传统按钮
            "button.jobs-description__footer-button",
            ".jobs-description__content button",
            "button.show-more-less-html__button",
            "button[data-tracking-control-name*='see_more']",
            # 通用展开按钮
            ".artdeco-card button[aria-expanded='false']",
            "footer button",
            # 带"more"文本的按钮
            "button"
        ]
        
        clicked = False
        for selector in see_more_selectors:
            try:
                buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    btn_text = btn.text.lower().strip()
                    # 检查按钮文本是否包含展开相关关键词
                    if any(kw in btn_text for kw in ['more', 'show', 'see', '展开', '更多', '…']):
                        try:
                            # 使用JavaScript点击，更可靠
                            self.browser.execute_script("arguments[0].click();", btn)
                            time.sleep(0.8)
                            clicked = True
                            log.debug(f"点击了展开按钮: {btn_text}")
                            break
                        except:
                            continue
                if clicked:
                    break
            except:
                continue
        
        # 如果没找到带文本的按钮，尝试点击aria-label包含more的按钮
        if not clicked:
            try:
                more_btn = self.browser.find_element(By.XPATH, "//button[contains(@aria-label, 'more') or contains(@aria-label, 'More')]")
                self.browser.execute_script("arguments[0].click();", more_btn)
                time.sleep(0.8)
                log.debug("通过XPath点击了more按钮")
            except:
                pass
        
        # 尝试多个选择器获取JD内容 - 基于实际页面结构
        jd_selectors = [
            # 新版LinkedIn - About the job 部分的内容
            "span[class*='eff879ea']",  # 实际页面中的class
            "[data-testid='expandable-text-box']",  # 有 data-testid 的元素
            "div[data-sdui-component*='aboutTheJob'] p",  # aboutTheJob 组件
            "div[data-sdui-component='cta-section-with-header']",  # CTA section
            # 传统选择器
            "div.jobs-description__content",
            "div.jobs-description-content__text",
            "div#job-details",
            "div.jobs-box__html-content",
            "article.jobs-description__container",
            "div[class*='jobs-description']",
            "div.description__text",
            ".show-more-less-html__markup",
            # 通用选择器
            "[class*='description-content']",
            "[class*='job-description']",
        ]
        
        for selector in jd_selectors:
            try:
                elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    if text and len(text) > 100:  # 确保获取到有意义的内容
                        log.debug(f"通过选择器 {selector} 获取到JD ({len(text)} 字符)")
                        return text
            except Exception as e:
                log.debug(f"选择器 {selector} 失败: {e}")
                continue
        
        # 尝试通过 XPath 获取 main 元素的文本
        try:
            main_element = self.browser.find_element(By.TAG_NAME, "main")
            text = main_element.text.strip()
            log.debug(f"main 元素文本长度: {len(text)}")
            if text and len(text) > 200:
                # 提取主要内容（跳过头部信息）
                lines = text.split('\n')
                # 找到 "About the job" 后面的内容
                start_idx = 0
                for i, line in enumerate(lines):
                    if 'About the job' in line or 'about the job' in line.lower():
                        start_idx = i + 1
                        break
                if start_idx > 0:
                    result = '\n'.join(lines[start_idx:])
                    log.debug(f"从 main 元素提取JD ({len(result)} 字符)")
                    return result
                # 如果没有找到 "About the job"，返回整个 main 文本
                log.debug(f"未找到 'About the job'，返回完整 main 文本")
                return text
        except Exception as e:
            log.debug(f"获取 main 元素失败: {e}")
        
        log.warning("无法获取JD内容")
        return ""
    
    def _get_posted_time(self) -> str:
        """获取发布时间"""
        try:
            element = self.browser.find_element(
                By.CSS_SELECTOR, "span.jobs-unified-top-card__posted-date"
            )
            return element.text.strip()
        except:
            return ""
    
    def _get_applicants_count(self) -> str:
        """获取申请人数"""
        try:
            element = self.browser.find_element(
                By.CSS_SELECTOR, "span.jobs-unified-top-card__applicant-count"
            )
            return element.text.strip()
        except:
            return ""
    
    def scrape_jobs(self, position: str, location: str, 
                    max_pages: int = 5, experience_levels: List[int] = None,
                    geo_id: str = None, time_filter: str = None, 
                    distance: int = None, sort_by: str = "DD",
                    pre_filter: bool = True,
                    ai_pre_filter: bool = False, ai_scorer: Any = None,
                    pages_before_detail: int = 3,
                    start_page: int = 0,
                    list_only: bool = False,
                    progress_manager: Any = None) -> List[JobListing]:
        """爬取多页岗位
        
        Args:
            position: 职位关键词
            location: 地点
            max_pages: 最大爬取页数（从 start_page 开始计算）
            experience_levels: 经验级别筛选
            geo_id: 地理位置ID (如 101282230 = Germany)
            time_filter: 时间过滤器 (r86400=24小时, r259200=三天, r604800=一周, r2592000≈一个月)
            distance: 距离范围(公里)；location 为 Remote 时不加入 URL（避免 LinkedIn 绑定个人所在城市半径）
            sort_by: 排序方式 (DD=最新发布, R=相关度)
            pre_filter: 是否启用关键词预过滤
            ai_pre_filter: 是否启用AI预过滤（攒多页后用AI筛选）
            ai_scorer: AIScorer实例（用于AI预过滤）
            pages_before_detail: 攒多少页后再进入详情页（配合ai_pre_filter使用）
            start_page: 从第几页开始爬取 (0-indexed)
            list_only: 是否只爬取列表（不进入详情页）
            progress_manager: 进度管理器（用于过滤已爬取详情的岗位）
        
        Returns:
            岗位列表
        """
        all_jobs = []
        all_list_jobs = []  # 存储列表页的岗位信息
        
        # 计算实际爬取的页数范围
        end_page = start_page + max_pages
        log.info(f"爬取范围: 第 {start_page + 1} 页到第 {end_page} 页 (共 {max_pages} 页)")
        
        # 每页：写进度 → 打开 URL → 判零结果横幅 → 列表模式或直抓详情
        for page in range(start_page, end_page):
            log.info(f"正在爬取第 {page + 1} 页 (本次第 {page - start_page + 1}/{max_pages} 页)...")
            
            # 续爬依赖此文件；记录「即将抓取」的页码（0-based）
            self._save_crawl_progress(position, location, page, sort_by=sort_by)
            
            # --- 拼装分页 URL（LinkedIn 列表每页约 25 条，start=0,25,50,...）---
            start = page * 25
            base_url = "https://www.linkedin.com/jobs/search/?"
            loc_stripped = (location or "").strip()
            is_remote_place = loc_stripped.lower() == "remote"
            params = [
                f"keywords={quote_plus(position)}",
                f"start={start}"
            ]
            
            # 添加地理位置
            if geo_id:
                params.append(f"geoId={geo_id}")
            else:
                params.append(f"location={quote_plus(loc_stripped)}")
            
            # 添加时间过滤器
            if time_filter:
                params.append(f"f_TPR={time_filter}")
            
            # 距离会与 LinkedIn 账户/会话的默认城市绑定，导致「Remote」仍被限制在某国/地区；Remote 地点不传 distance
            if distance and not is_remote_place:
                params.append(f"distance={distance}")
            
            # Remote 岗位筛选（On-site=1, Remote=2, Hybrid=3）
            if is_remote_place:
                params.append("f_WT=2")
            
            # 添加排序
            if sort_by:
                params.append(f"sortBy={sort_by}")
            
            # 添加经验级别
            if experience_levels:
                exp_str = ",".join(map(str, experience_levels))
                params.append(f"f_E={exp_str}")
            
            url = base_url + "&".join(params)
            log.info(f"URL: {url}")
            self.browser.get(url)
            time.sleep(random.uniform(4, 6))  # 列表与空状态文案依赖前端渲染，略加长等待

            # 显式零结果页：无需再翻 max_pages，结束本组 position×location
            if self._page_indicates_no_matching_jobs():
                log.info(
                    "检测到 LinkedIn「无匹配职位」空页面（如 No matching jobs found），"
                    "停止当前关键词/地点的翻页抓取"
                )
                break
            
            # --- 分支 A：攒列表 + AI 粗筛后再进详情；分支 B：每页直接进详情 ---
            if ai_pre_filter and ai_scorer:
                # AI预过滤模式：先收集列表信息
                jobs_info = self.get_jobs_from_list_page()
                no_data_page = len(jobs_info) == 0
                
                # 先用关键词预过滤
                if pre_filter:
                    filtered_jobs = []
                    for job in jobs_info:
                        should_skip, reason = self._should_skip_job(job["title"], job["company"])
                        if should_skip:
                            log.info(f"[关键词过滤] {job['title']} @ {job['company']} | {reason}")
                        else:
                            filtered_jobs.append(job)
                    jobs_info = filtered_jobs
                
                # 去重：检查历史记录
                before_dedup = len(jobs_info)
                jobs_info = self.deduplicator.deduplicate_list(jobs_info)
                if before_dedup > len(jobs_info):
                    log.info(f"[去重] 本页移除 {before_dedup - len(jobs_info)} 个历史重复岗位")
                
                # 去重：过滤掉已爬取过详情的岗位（基于 job_id）
                if progress_manager:
                    before_pm = len(jobs_info)
                    jobs_info = progress_manager.filter_new_jobs(jobs_info)
                    if before_pm > len(jobs_info):
                        log.info(f"[进度去重] 本页移除 {before_pm - len(jobs_info)} 个已处理岗位")
                
                all_list_jobs.extend(jobs_info)
                log.info(f"第 {page + 1} 页收集到 {len(jobs_info)} 个岗位，累计 {len(all_list_jobs)} 个")
                
                # 每pages_before_detail页或最后一页进行AI过滤并爬取详情
                pages_crawled = page - start_page + 1
                is_batch_complete = pages_crawled % pages_before_detail == 0
                # 当页面无数据时，视为当前条件已到底部，触发本批最后处理并结束该条件爬取
                is_last_page = (page == end_page - 1) or no_data_page
                
                if (is_batch_complete or is_last_page) and all_list_jobs:
                    # 如果是 list_only 模式，只保存列表不进入详情页
                    if list_only:
                        self._save_list_jobs(all_list_jobs, position, location)
                        log.info(f"[list_only] 已保存 {len(all_list_jobs)} 个岗位到列表文件")
                        all_list_jobs = []
                        continue
                    
                    if all_list_jobs:
                        log.info(f"\n>>> 开始AI粗过滤 {len(all_list_jobs)} 个岗位...")
                        # 使用 return_all=True 获取所有结果以便记录原因
                        all_pre_filtered_results = ai_scorer.ai_pre_filter(all_list_jobs, return_all=True)
                        
                        passed_jobs = [j for j in all_pre_filtered_results if j.get('pre_filter_passed', True)]
                        filtered_jobs = [j for j in all_pre_filtered_results if not j.get('pre_filter_passed', True)]
                        
                        log.info(f"AI粗过滤结果: {len(passed_jobs)} 个岗位通过, {len(filtered_jobs)} 个被过滤")
                        
                        # 保存过滤掉的岗位，以便用户查看原因
                        if filtered_jobs:
                            self._save_filtered_jobs(filtered_jobs)

                        # 爬取通过AI过滤的岗位详情
                        for idx, job_info in enumerate(passed_jobs, 1):
                            try:
                                log.info(f"正在获取详情 ({idx}/{len(passed_jobs)}): {job_info['title']}")
                                job = self.get_job_details(job_info["job_id"])
                                if job:
                                    # 将预筛选原因附加到JobListing对象
                                    if job_info.get('pre_filter_reason'):
                                        job_reason = job_info['pre_filter_reason']
                                        # 如果是对象（有时候llm返回结构会变），转str
                                        if not isinstance(job_reason, str):
                                            job_reason = str(job_reason)
                                        job.ai_reason = f"[AI初筛] {job_reason}"
                                    
                                    all_jobs.append(job)
                                    
                                    # 添加到去重
                                    self.deduplicator.add(job.title, job.company)
                                    self._save_progress(all_jobs)
                            except Exception as e:
                                log.error(f"抓取岗位 {job_info['job_id']} 出错: {e}")
                                self._save_progress(all_jobs)
                                # 保存历史记录
                                self.deduplicator.save_history()
                                return all_jobs
                            
                            delay = random.uniform(2, 5)
                            time.sleep(delay)
                        
                        all_list_jobs = []  # 清空列表，准备下一批

                # 无数据页：结束当前 position+location 条件，进入下一个任务
                if no_data_page:
                    log.info(f"第 {page + 1} 页无数据，结束当前条件爬取并切换到下一项任务")
                    break
            else:
                # 原有模式：每页直接爬取详情
                job_ids = self.get_job_ids_from_page(pre_filter=pre_filter)
                
                if not job_ids:
                    log.info("没有更多岗位了")
                    break
                
                for idx, job_id in enumerate(job_ids, 1):
                    try:
                        log.info(f"正在获取详情 ({idx}/{len(job_ids)}): {job_id}")
                        job = self.get_job_details(job_id)
                        if job:
                            # 去重检查
                            if self.deduplicator.is_duplicate(job.title, job.company):
                                log.info(f"[历史重复] 跳过: {job.title} @ {job.company}")
                                continue
                            all_jobs.append(job)
                            self.deduplicator.add(job.title, job.company)
                            self._save_progress(all_jobs)
                    except Exception as e:
                        log.error(f"抓取岗位 {job_id} 出错: {e}")
                        self._save_progress(all_jobs)
                        self.deduplicator.save_history()
                        return all_jobs
                    
                    delay = random.uniform(2, 5)
                    time.sleep(delay)
        
        # 保存历史记录
        self.deduplicator.save_history()
        
        self.jobs = all_jobs
        return all_jobs
    
    def _save_progress(self, jobs: List[JobListing]) -> None:
        """保存抓取进度（增量保存 + title+company 去重）"""
        try:
            import json
            progress_file = _out_file('jobs_progress.json')
            
            # 加载现有数据
            existing = []
            if os.path.exists(progress_file):
                with open(progress_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            
            # 状态优先级
            status_priority = {'applied': 5, 'closed': 4, 'failed': 3, 'resume_generated': 2, 'pending': 1}
            
            def get_priority(job):
                if isinstance(job, dict):
                    return (status_priority.get(job.get('status', ''), 0), job.get('ai_score', 0))
                return (0, getattr(job, 'ai_score', 0) or 0)
            
            def make_key(job):
                if isinstance(job, dict):
                    title = job.get('title', '').lower().strip()
                    company = job.get('company', '').lower().strip()
                else:
                    title = (job.title or '').lower().strip()
                    company = (job.company or '').lower().strip()
                return f"{title}|||{company}"
            
            # 构建现有数据的索引
            seen = {}
            for job in existing:
                key = make_key(job)
                if key not in seen or get_priority(job) > get_priority(seen[key]):
                    seen[key] = job
            
            # 合并新数据
            new_count = 0
            for job in jobs:
                job_dict = asdict(job) if not isinstance(job, dict) else job
                key = make_key(job_dict)
                if key not in seen or get_priority(job_dict) > get_priority(seen[key]):
                    if key not in seen:
                        new_count += 1
                    seen[key] = job_dict
            
            # 保存
            all_jobs = list(seen.values())
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(all_jobs, f, ensure_ascii=False, indent=2)
            log.info(f"进度已保存: 新增 {new_count}, 累计 {len(all_jobs)} 个岗位")
        except Exception as e:
            log.error(f"保存进度失败: {e}")
    
    def _save_crawl_progress(self, position: str, location: str, current_page: int, sort_by: str = None) -> None:
        """保存爬取分页进度，以便下次继续"""
        progress_file = _out_file('crawl_progress.json')
        try:
            progress = {}
            if os.path.exists(progress_file):
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
            
            # 使用 sort_by 作为 key 的一部分
            key_suffix = f"|{sort_by}" if sort_by else ""
            key = f"{position}|{location}{key_suffix}"
            
            progress[key] = {
                'position': position,
                'location': location,
                'sort_by': sort_by,
                'last_page': current_page,
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"保存分页进度失败: {e}")
    
    def _save_list_jobs(self, jobs: List[dict], position: str, location: str) -> None:
        """保存列表页岗位到文件（用于 list_only 模式）"""
        list_file = _out_file('jobs_list_cache.json')
        try:
            existing = []
            if os.path.exists(list_file):
                with open(list_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            
            # 基于 title+company 去重（而不是 job_id，因为同一职位可能有多个 job_id）
            def make_key(job):
                title = job.get('title', '').lower().strip()
                company = job.get('company', '').lower().strip()
                return f"{title}|||{company}"
            
            existing_keys = set(make_key(j) for j in existing)
            
            added_count = 0
            for job in jobs:
                key = make_key(job)
                if key not in existing_keys:
                    job['_position'] = position
                    job['_location'] = location
                    job['_scraped_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    existing.append(job)
                    existing_keys.add(key)
                    added_count += 1
            
            with open(list_file, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            
            log.info(f"已保存列表缓存: 新增 {added_count}, 累计 {len(existing)} 个岗位")
        except Exception as e:
            log.error(f"保存列表缓存失败: {e}")
    
    @staticmethod
    def get_crawl_progress(position: str, location: str, sort_by: str = None) -> int:
        """获取上次爬取的页数，用于续爬（跨天自动重置为 0）。"""
        progress_file = _out_file('crawl_progress.json')
        try:
            if os.path.exists(progress_file):
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                    
                    # 尝试查找对应的 key
                    key_suffix = f"|{sort_by}" if sort_by else ""
                    key = f"{position}|{location}{key_suffix}"
                    
                    if key in progress:
                        item = progress[key] or {}
                        # 按自然日续爬：仅当天沿用 last_page，跨天从第 1 页重新开始
                        updated_at = str(item.get('updated_at', '')).strip()
                        if updated_at:
                            try:
                                last_date = datetime.strptime(updated_at, '%Y-%m-%d %H:%M:%S').date()
                                if last_date != datetime.now().date():
                                    log.info(
                                        f"[续爬重置] 检测到跨天（{last_date} -> {datetime.now().date()}），"
                                        f"{position}@{location} 从第 1 页开始"
                                    )
                                    return 0
                            except Exception:
                                # 时间格式异常时保守重置，避免意外跳页
                                log.warning(
                                    f"[续爬重置] crawl_progress 时间格式异常: {updated_at}，"
                                    f"{position}@{location} 从第 1 页开始"
                                )
                                return 0
                        return int(item.get('last_page', 0) or 0)
                    
                    # 如果未指定 sort_by (None)，但也可能不需要 fallback，
                    # 只有当用户没有 sort_by 要求时（默认为 Relevance?）
                    # 这里保持简单：如果没有完全匹配，就返回0
        except:
            pass
        return 0

    def close(self) -> None:
        """关闭浏览器"""
        if self.browser:
            self.browser.quit()
            log.info("浏览器已关闭")


class JobFilter:
    """岗位过滤器"""
    
    # 德语语言要求关键词 - 只匹配明确要求德语能力的表述
    # 不包括: germany, deutschland, deutsch (单独出现), german (单独出现)
    GERMAN_REQUIRED_PATTERNS = [
        # 德语 - 明确的语言能力要求
        r'fließend\s+deutsch',                  # fließend deutsch (流利德语)
        r'deutsch(?:kenntnisse|sprachkenntnisse)',  # deutschkenntnisse (德语能力)
        r'muttersprache\s+deutsch',             # muttersprache deutsch (德语母语)
        r'verhandlungssicher\s+deutsch',        # verhandlungssicher deutsch (商务德语)
        r'gute\s+deutsch',                      # gute deutsch... (好的德语...)
        r'sehr\s+gute\s+deutsch',               # sehr gute deutsch... (很好的德语...)
        r'deutsch\s+(?:in\s+wort\s+und\s+schrift|fließend|erforderlich|zwingend)',  # deutsch in wort und schrift (德语读写)
        r'sprache[:\s]+deutsch',                # sprache: deutsch (语言: 德语)
        r'deutsch\s*\([abc][12]',               # deutsch (C1 / deutsch (B2 等
        
        # 英语 - 明确要求德语能力
        r'fluent\s+(?:in\s+)?german',           # fluent german / fluent in german
        r'german\s+(?:language\s+)?(?:required|mandatory|essential|necessary)',  # german required
        r'german\s+speak(?:er|ing)',            # german speaker / german speaking
        r'native\s+german',                     # native german
        r'strong\s+(?:communicat\w+\s+(?:in\s+)?)?german',  # strong communicator in german
        r'(?:excellent|proficient|advanced)\s+german',  # excellent/proficient german
        r'german\s+(?:communication|proficiency|fluency)',  # german communication/proficiency
        r'c[12]\s+(?:level\s+)?german',         # C1/C2 german
        r'german\s+c[12]',                      # german C1/C2
        r'business\s+level\s+german',           # business level german
    ]
    
    # 经验年限提取模式
    EXPERIENCE_PATTERNS = [
        r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of)?\s*experience',
        r'(\d+)\+?\s*(?:years?|yrs?)',
        r'experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)',
        r'minimum\s*(\d+)\s*(?:years?|yrs?)',
        r'at least\s*(\d+)\s*(?:years?|yrs?)',
        r'(\d+)\s*-\s*\d+\s*(?:years?|yrs?)',
    ]
    
    def __init__(
        self,
        max_experience_years: int = 5,
        min_experience_years: int = 0,
        reject_german_jd: bool = True,
    ):
        self.max_experience_years = max_experience_years
        self.min_experience_years = min_experience_years
        self.reject_german_jd = reject_german_jd
        # 预编译正则表达式
        self._german_patterns = [re.compile(p, re.IGNORECASE) for p in self.GERMAN_REQUIRED_PATTERNS]
        
        # 德语常用词（用于检测JD主体是否为德语）— 一律用小写，匹配时已 lower
        self._german_common_words = [
            'und', 'die', 'der', 'das', 'für', 'wir', 'mit', 'sie', 'auf', 'ist',
            'von', 'den', 'ein', 'eine', 'zu', 'bei', 'sind', 'werden', 'nach', 'sich',
            'deine', 'dein', 'unser', 'unsere', 'oder', 'als', 'auch', 'nicht', 'haben',
            'aufgaben', 'anforderungen', 'profil', 'über', 'uns', 'qualifikationen',
            'entwickler', 'ingenieur', 'mitarbeiter', 'abteilung', 'vollzeit', 'bewerbung',
        ]
        headings_re = (
            r'ihre\s+aufgaben|ihr\s+profil|wir\s+bieten|über\s+uns|bewerbung|voraussetzungen|wir\s+suchen|'
            r'stellenbeschreibung|aufgabenprofil|anforderungen|qualifikationen|unser\s+angebot|'
            r'das\s+bringen\s+sie|deine\s+aufgaben|dein\s+profil|erfolgreiche\s+bewerbung'
        )
        self._german_section_markers = re.compile(headings_re, re.IGNORECASE)
    
    def _is_german_jd(self, text: str) -> bool:
        """检测岗位标题+JD 是否主要为德语（统计常用德语词 + 典型德语板块标题）。"""
        if not text or not str(text).strip():
            return False
        
        text_lower = text.lower()
        total_words = len(text_lower.split())
        if total_words == 0:
            return False
        
        german_word_count = 0
        for word in self._german_common_words:
            count = len(re.findall(rf'\b{re.escape(word)}\b', text_lower))
            german_word_count += count
        
        # 短 JD：典型德语小标题或足够多的德语高频词则视为德语
        if total_words < 50:
            if self._german_section_markers.search(text_lower):
                return True
            return german_word_count >= 8
        
        ratio = german_word_count / total_words
        return ratio > 0.1 or german_word_count >= 30
    
    def is_mostly_german_job_text(self, title: str, jd: str) -> bool:
        """与 filter_job 使用同一套规则，供 pipeline 等 dict 场景复用。"""
        return self._is_german_jd(f"{title or ''}\n{jd or ''}")
    
    def is_english_job(self, job: JobListing) -> bool:
        """检查是否为英文岗位（不要求德语）
        
        返回 False 的情况:
        1. JD主体是德语写的
        2. JD中明确要求德语能力 (fluent german, deutsch C1, etc.)
        """
        jd = job.job_description or ""
        title = job.title or ""
        text = f"{title}\n{jd}"
        
        # 检查1: 标题+JD 主体是否为德语
        if self._is_german_jd(text):
            return False
        
        # 检查2: 是否明确要求德语能力
        for pattern in self._german_patterns:
            if pattern.search(text):
                return False
        
        return True
    
    def extract_experience_years(self, job: JobListing) -> Optional[int]:
        """从JD中提取经验要求年限"""
        jd_lower = job.job_description.lower()
        
        min_years = None
        for pattern in self.EXPERIENCE_PATTERNS:
            matches = re.findall(pattern, jd_lower)
            if matches:
                for match in matches:
                    years = int(match)
                    if min_years is None or years < min_years:
                        min_years = years
        
        return min_years
    
    def filter_job(self, job: JobListing) -> JobListing:
        """过滤单个岗位
        
        硬性过滤:
        - JD/标题主体为德语（可配置关闭，见 reject_german_jd / filter_german_jobs）
        - 经验年限过高/过低
        - 明确要求德语流利/C1/C2作为必须条件
        """
        jd = job.job_description or ""
        text = f"{job.title}\n{jd}"
        
        job.experience_years = self.extract_experience_years(job)
        
        if self.reject_german_jd and self._is_german_jd(text):
            job.passed_filter = False
            job.is_english = False
            job.ai_reason = "JD主体为德语"
            return job
        
        # 检查是否有硬性德语要求 (只匹配最严格的要求)
        # 更宽松的德语要求交给AI评分判断
        hard_german_patterns = [
            # 英文表述
            re.compile(r'german\s+(?:language\s+)?(?:required|mandatory|essential)', re.IGNORECASE),
            re.compile(r'fluent\s+(?:in\s+)?german', re.IGNORECASE),
            re.compile(r'native\s+german', re.IGNORECASE),
            re.compile(r'german\s+c[12]', re.IGNORECASE),
            re.compile(r'c[12]\s+(?:level\s+)?german', re.IGNORECASE),
            # 德文表述
            re.compile(r'muttersprache\s+deutsch', re.IGNORECASE),
            re.compile(r'verhandlungssicher\s+deutsch', re.IGNORECASE),
            re.compile(r'deutsch\s*\(?\s*(?:mindestens\s+)?c[12]', re.IGNORECASE),  # deutsch (mindestens c1)
            re.compile(r'fließend\s+deutsch', re.IGNORECASE),  # fließend deutsch
            re.compile(r'deutsch\s+(?:und\s+englisch\s+)?(?:in\s+wort\s+und\s+schrift\s+)?fließend', re.IGNORECASE),  # deutsch ... fließend
        ]
        
        requires_hard_german = any(p.search(text) for p in hard_german_patterns)
        
        # 标记德语相关信息 (供AI评分参考)
        job.is_english = not requires_hard_german
        
        # 判断是否通过过滤
        if requires_hard_german:
            job.passed_filter = False
            job.ai_reason = "要求德语流利/C1以上"
        elif job.experience_years and job.experience_years > self.max_experience_years:
            job.passed_filter = False
            job.ai_reason = f"经验要求过高 ({job.experience_years}年)"
        elif job.experience_years is not None and job.experience_years < self.min_experience_years:
            job.passed_filter = False
            job.ai_reason = f"经验要求过低 ({job.experience_years}年)"
        else:
            job.passed_filter = True
        
        return job
    
    def filter_jobs(self, jobs: List[JobListing]) -> tuple[List[JobListing], List[JobListing]]:
        """过滤岗位列表
        
        Returns:
            (通过过滤的岗位列表, 未通过过滤的岗位列表)
        """
        passed = []
        filtered_out = []
        
        for job in jobs:
            job = self.filter_job(job)
            if job.passed_filter:
                passed.append(job)
            else:
                filtered_out.append(job)
                # 记录被过滤的岗位
                log.info(f"[过滤] {job.title} @ {job.company} | 原因: {job.ai_reason}")
        
        log.info(f"过滤结果: {len(passed)} 通过, {len(filtered_out)} 被过滤")
        
        # 打印被过滤岗位汇总
        if filtered_out:
            log.info("=" * 40)
            log.info("被过滤岗位明细:")
            for i, job in enumerate(filtered_out, 1):
                log.info(f"  {i}. {job.title} @ {job.company} - {job.ai_reason}")
            log.info("=" * 40)
        
        return passed, filtered_out


class JobProgressManager:
    """岗位进度管理器 - 管理已爬取、已申请的岗位状态
    
    文件说明:
    - jobs_progress.json: 当前爬取进度（临时，包含详情但未申请的岗位）
    - jobs_applied.json: 已申请的岗位（长期存储，下次启动时跳过）
    - jobs_scraped_ids.json: 已爬取过详情的岗位ID（避免重复爬取详情）
    """
    
    PROGRESS_FILE = _out_file('jobs_progress.json')
    APPLIED_FILE = _out_file('jobs_applied.json')
    SCRAPED_IDS_FILE = _out_file('jobs_scraped_ids.json')
    
    def __init__(self):
        self.applied_ids: set = self._load_applied_ids()
        self.scraped_ids: set = self._load_scraped_ids()
        self.existing_title_companies: set = self._load_existing_title_companies()
        log.info(f"进度管理器: 已申请{len(self.applied_ids)}个, 已爬取详情{len(self.scraped_ids)}个, 已存在{len(self.existing_title_companies)}个")
    
    def _load_existing_title_companies(self) -> set:
        """从 jobs_progress.json 加载已存在的 title+company 组合"""
        try:
            if os.path.exists(self.PROGRESS_FILE):
                with open(self.PROGRESS_FILE, 'r', encoding='utf-8') as f:
                    jobs = json.load(f)
                    title_companies = set()
                    for job in jobs:
                        title = self._normalize(job.get('title', ''))
                        company = self._normalize(job.get('company', ''))
                        if title and company:
                            # 存储标准化后的 key
                            title_companies.add(f"{title}|||{company}")
                            
                            # 同时存储原始 key 以防万一
                            raw_title = job.get('title', '').lower().strip()
                            raw_company = job.get('company', '').lower().strip()
                            title_companies.add(f"{raw_title}|||{raw_company}")
                            
                    log.info(f"JobProgressManager: 从 jobs_progress.json 加载了 {len(title_companies)} 个已存在指纹")
                    return title_companies
        except Exception as e:
            log.warning(f"加载已存在岗位失败: {e}")
        return set()
    
    def _normalize(self, text: str) -> str:
        """标准化文本（移除标点、括号内容、常见后缀）"""
        if not text: return ""
        text = text.lower()
        # 移除 (m/f/d), (gn) 等
        import re
        text = re.sub(r'[\(\[].*?[\)\]]', '', text)
        # 移除常见公司后缀
        for suffix in [' inc', ' gmbh', ' ag', ' limited', ' ltd', ' co', ' corp', ' llc', ' srl', ' sa', ' ab']:
            if text.endswith(suffix) or text.endswith(suffix + '.'):
                text = text.replace(suffix, '')
        # 只保留字母和数字
        text = re.sub(r'[^a-z0-9]', '', text)
        return text

    def _load_applied_ids(self) -> set:
        """加载已申请的岗位ID"""
        try:
            if os.path.exists(self.APPLIED_FILE):
                with open(self.APPLIED_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(item.get('job_id') for item in data if item.get('job_id'))
        except Exception as e:
            log.warning(f"加载已申请岗位失败: {e}")
        return set()
    
    def _load_scraped_ids(self) -> set:
        """加载已爬取详情的岗位ID"""
        try:
            if os.path.exists(self.SCRAPED_IDS_FILE):
                with open(self.SCRAPED_IDS_FILE, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
        except Exception as e:
            log.warning(f"加载已爬取ID失败: {e}")
        return set()
    
    def _save_scraped_ids(self):
        """保存已爬取的岗位ID"""
        try:
            with open(self.SCRAPED_IDS_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(self.scraped_ids), f)
        except Exception as e:
            log.error(f"保存已爬取ID失败: {e}")
    
    def is_already_applied(self, job_id: str) -> bool:
        """检查岗位是否已申请"""
        return job_id in self.applied_ids
    
    def is_already_scraped(self, job_id: str) -> bool:
        """检查岗位详情是否已爬取"""
        return job_id in self.scraped_ids
    
    def mark_as_scraped(self, job_id: str):
        """标记岗位详情已爬取"""
        self.scraped_ids.add(job_id)
        self._save_scraped_ids()
    
    def mark_as_applied(self, job: dict):
        """标记岗位已申请"""
        self.applied_ids.add(job.get('job_id'))
        # 追加到已申请文件
        try:
            applied_jobs = []
            if os.path.exists(self.APPLIED_FILE):
                with open(self.APPLIED_FILE, 'r', encoding='utf-8') as f:
                    applied_jobs = json.load(f)
            
            # 添加申请时间
            job['applied_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            applied_jobs.append(job)
            
            with open(self.APPLIED_FILE, 'w', encoding='utf-8') as f:
                json.dump(applied_jobs, f, ensure_ascii=False, indent=2)
            
            log.info(f"已标记为申请: {job.get('title')} @ {job.get('company')}")
        except Exception as e:
            log.error(f"保存申请记录失败: {e}")
    
    def filter_new_jobs(self, jobs: List[dict]) -> List[dict]:
        """过滤掉已申请、已爬取详情、已存在的岗位
        
        Args:
            jobs: [{"job_id": "xxx", "title": "xxx", "company": "xxx", ...}, ...]
        
        Returns:
            需要处理的新岗位列表
        """
        new_jobs = []
        skipped_applied = 0
        skipped_scraped = 0
        skipped_existing = 0
        
        for job in jobs:
            job_id = job.get('job_id')
            title = job.get('title', '')
            company = job.get('company', '')
            
            # 1. 检查 raw key (简单处理)
            raw_key = f"{title.lower().strip()}|||{company.lower().strip()}"
            
            # 2. 检查 normalized key (高级去重)
            norm_title = self._normalize(title)
            norm_company = self._normalize(company)
            norm_key = f"{norm_title}|||{norm_company}"
            
            if self.is_already_applied(job_id):
                skipped_applied += 1
            elif self.is_already_scraped(job_id):
                skipped_scraped += 1
            # 检查两种 keys 是否存在
            elif raw_key in self.existing_title_companies or norm_key in self.existing_title_companies:
                skipped_existing += 1
                log.debug(f"[跳过-已存在] {title} @ {company}")
            else:
                new_jobs.append(job)
        
        if skipped_applied > 0 or skipped_scraped > 0 or skipped_existing > 0:
            log.info(f"跳过: {skipped_applied}个已申请, {skipped_scraped}个已爬取详情, {skipped_existing}个已存在")
        
        return new_jobs
    
    def clear_progress(self):
        """清理临时进度文件（申请完成后调用）"""
        try:
            if os.path.exists(self.PROGRESS_FILE):
                os.remove(self.PROGRESS_FILE)
                log.info("已清理临时进度文件")
        except Exception as e:
            log.warning(f"清理进度文件失败: {e}")


class AIScorer:
    """AI评分器 - 使用Gemini批量分析JD与简历的匹配度"""
    # 按 1M tokens 的估算单价（USD）
    GEMINI_FLASH_INPUT_PRICE = 0.075
    GEMINI_FLASH_OUTPUT_PRICE = 0.30
    GPT4_INPUT_PRICE = 30.0
    GPT4_OUTPUT_PRICE = 60.0
    
    # AI预过滤Prompt模板（粗过滤，只过滤明显不合适的）
    PRE_FILTER_PROMPT = """你是一个求职顾问。请根据候选人简历，判断以下岗位是否值得进一步了解。

## 候选人简历
{resume_text}

## 候选人核心诉求
1. **主要目标**: 前端开发或全栈开发（优先 React / TypeScript / Vue / React Native）。
2. **次要目标**: AI 应用工程相关岗位（LLM/RAG/Agent）且技术栈与前端/全栈有交集。
3. **首选（偏好，非硬性过滤）**: **全职**（Full-time / Permanent，或等同的长期雇佣）且 JD 或标题能看出 **明确签证/工签赞助/relocation support** 的岗位，在方向匹配时视为**最优先**；在 `reason` 中可写「首选：全职+签证」。
4. **亦接受**: Freelancer、Contractor、零工、短期合同、项目制、兼职等与工程开发相关的形式；**不因**无签证说明或灵活用工而直接过滤，但优先级低于「首选」。
5. **签证信息**: 不因「未写签证」或「写明不提供签证」而机械过滤（由候选人自行判断）；若同时满足首选条件，务必在 `reason` 里突出。

## 系统细评排序优先级（列表页仅有标题时可忽略；有JD后由程序自动分档）
岗位经技能/关键词评分后，最终展示顺序为：**先按下面档位 1→5 分桶，同一档位内再按匹配分从高到低**：
1. 有签证支持的瑞士软件行业岗位
2. 有签证支持的德国 Remote 岗位
3. 有签证支持的德国 Hybrid 岗位
4. 远程岗位（全球，含未写签证者）
5. 兼职岗位（含 Part-time / Teilzeit / 零工类）

### 🚫 黑名单公司 (直接过滤):
- none

## 待筛选岗位列表（只有标题和公司）
{jobs_text}

## 筛选与过滤规则
请严格按照以下逻辑判断：

**❌ 必须过滤 (keep: false)**:
1. **方向不匹配**: 纯销售(Sales)、纯运营(Ops)、纯项目管理/产品管理（无工程开发要求）。
2. **纯后端且技术栈偏离**: 仅 .NET/Go/PHP 维护型 CRUD，且无前端职责、无工程落地职责时过滤。对 Java/Spring/Python/FastAPI 后端工程岗位可保留（尤其有 API 设计、性能优化、分布式、工程化实践）。
3. **级别过高**: Director, VP, Chief, Head of, Principal（明显管理层或超资深策略岗）。
4. **强德语门槛**: 标题/JD 明确 "German speaking required", "Fluent German", "C1/C2 German required"。
5. **低匹配站点类岗位**: 以 WordPress/Shopify 页面搭建为主、工程复杂度低且与候选人核心能力不匹配。
6. **不确定岗位**: 标题信息模糊，无法判断与前端/全栈目标匹配时，默认过滤。

**✅ 必须保留 (keep: true)**:
1. **前端核心岗位**: Frontend Engineer/Developer, React Engineer, Vue Engineer, Angular Engineer, Web Frontend Engineer。
2. **全栈偏前端岗位**: Full-Stack Engineer/Developer，且包含 React/Vue/TypeScript/Node/Python/Java 等工程开发职责。
3. **移动端相关岗位**: React Native Engineer/Developer，或明确要求 React Native。
4. **AI 应用工程岗位**: LLM/RAG/Agent/GenAI 方向，且岗位强调工程落地（application/engineering/deployment）。
5. **技术栈强匹配岗位**: 标题或职责出现 React, React Native, TypeScript, JavaScript, Redux, Vue, Angular, HTML, CSS, REST/GraphQL, FastAPI, Spring Boot 中多个关键项。
6. **首选命中（保留时强调）**: 全职 + 明确 visa / work permit / relocation / sponsorship 之一，且与前端/全栈/后端工程方向一致 → **keep: true**，`reason` 优先写清「首选：全职+签证」。
7. **Freelance/Contract/零工**: 标题或职责相关且与工程方向一致 → **keep: true**，`reason` 可写「灵活用工，次优先于全职+签证」。
8. **后端工程匹配（允许）**: Java/Spring/Python/FastAPI 后端工程岗位，若职责体现 API 设计、鉴权、性能、工程化实践，可保留。


## 输出要求
请返回 JSON 数组。**无论通过(true)还是过滤(false)，都必须提供具体的 `reason`**。
- `reason` (通过): 说明为什么匹配（例如："AI核心岗位" 或 "AI公司后端岗位"）。
- `reason` (过滤): 说明为什么不匹配（例如："纯后端无工程落地" 或 "纯销售无开发职责"）。

## 输出格式（严格JSON数组）
```json
[
    {{"job_id": "123", "title": "AI Engineer", "keep": true, "reason": "核心AI岗位，完全匹配"}},
    {{"job_id": "456", "title": "Backend Dev", "keep": true, "reason": "虽是后端，但公司是AI独角兽"}},
    {{"job_id": "789", "title": "Senior Java Dev", "keep": false, "reason": "纯传统后端，与AI无关"}},
    {{"job_id": "000", "title": "Freelance React Developer", "keep": true, "reason": "前端工程相关，接受 Freelance 形式"}}
]
```

只返回JSON数组，不要有其他内容。"""

    # 批量评分Prompt模板
    BATCH_SCORING_PROMPT = """你是一个专业的求职顾问。请分析以下多个岗位与候选人简历的匹配程度。

## 候选人简历
{resume_text}

## 候选人语言能力
- 英语: 流利 (主要工作语言)
- 中文: 母语
- 德语: B1水平 (日常交流可以，但不能作为工作语言)

## 待评估岗位列表
{jobs_text}

## 评估简历和岗位要求
阅读简历然后并评估呃这个人他能做什么就是通过这个简历呀契不契合这个工作然后有多契合这个工作他好来去投递，为每个岗位打分(0-100分)，并给出简短理由。

## 理由书写要求（必须遵守）
- `reason` 不能空，且要可执行、可解释。
- 当 `score < 60` 时，`reason` 必须明确写出低分原因（例如：语言硬性门槛、核心技术栈缺口、经验年限不符、岗位类型不符）。
- 若有多个扣分点，至少写出前 1-2 个最关键扣分点，不要只写笼统句子。
- 若 `missing_skills` 非空，`reason` 中应体现关键缺失能力。

## 首选加分（重要）
在按「德语要求评分规则」算出**基础匹配分**后，若岗位同时满足：**(1) 全职或长期雇佣**（Full-time / Permanent / unlimited contract 等，非纯 Freelance/日结零工）**(2) JD 明确写出签证/工签赞助或 relocation 支持**（如 visa sponsorship, work permit, Blue Card, relocation assistance），可在基础分上**额外 +3～8 分**（总分不超过 100），并在 `reason` 开头注明「首选：全职+签证」。  
灵活用工（Freelance/Contract/短期）不因此扣分，但通常**不加**此项首选加分。  
系统仍会按地点/签证等做**展示分档**排序，与上述加分可同时存在。

## ⚠️ 德语要求评分规则

### 🚫 黑名单公司 (直接打0分):
- none

### 🚫 打低分 (30分以下) 的情况 - 德语是硬性要求:
- 明确要求德语作为**工作语言** (Arbeitssprache Deutsch)
- 要求德语**流利/熟练/C1/C2级别**:
  - "Fluent German", "Fließend Deutsch", "Sehr gute Deutschkenntnisse"
  - "German C1/C2", "Deutsch C1", "Native German speaker"
  - "Verhandlungssicher Deutsch", "Muttersprache Deutsch"
  - "German language required/mandatory/essential"
- 德语是**必须条件** (must have, nicht nice to have)

### ✅ 不扣分的情况 - 德语是可选项:
- "German is a plus", "Nice to have: German"
- "German B1/B2 preferred" (候选人符合B1)
- "Basic German", "German helpful but not required"
- JD是德语写的，但没有明确要求德语作为工作语言
- 工作地点在德国，但工作语言是英语 (English working environment)

### 🔍 判断原则:
1. JD用德语写 ≠ 要求德语能力 (很多德国公司用德语写JD但团队用英语工作)
2. 只看**明确的语言要求**，不要猜测
3. 如果不确定，保留高分，让候选人自己判断

## 输出格式 (严格按照JSON数组格式返回)
```json
[
    {{
        "job_id": "岗位ID",
        "score": 85,
        "reason": "一句话说明匹配/不匹配原因",
        "matched_skills": ["Python", "LLM"],
        "missing_skills": ["Kubernetes"]
    }},
    ...
]
```

只返回JSON数组，不要有其他内容。"""

    _PRIORITY_LABELS = {
        1: "瑞士软件业+签证",
        2: "德国远程+签证",
        3: "德国混合办公+签证",
        4: "远程",
        5: "兼职",
        99: "其他",
    }

    @staticmethod
    def compute_priority_tier(job: "JobListing") -> int:
        """按候选人规则匹配优先级档位（越小越优先）。匹配顺序自上而下，命中即返回。"""
        loc = (job.location or "").lower()
        title = (job.title or "").lower()
        desc = (job.job_description or "").lower()
        head = desc[:4000]

        visa_markers = (
            "visa sponsorship",
            "sponsor visa",
            "sponsorship",
            "work permit",
            "relocation assistance",
            "relocation support",
            "immigration support",
            "immigration",
            "blue card",
            "eu blue card",
            "we sponsor",
        )
        blob = f"{loc} {title} {head}"
        has_visa = any(m in blob for m in visa_markers)

        swiss = any(
            s in loc
            for s in ("switzerland", "schweiz", "suisse", "svizzera")
        ) or any(
            c in blob[:800]
            for c in (
                " zürich",
                " zurich",
                " geneva",
                " genf",
                " basel",
                " bern",
                " berne",
                " lausanne",
                " winterthur",
                " st. gallen",
                " lugano",
            )
        )

        germany = any(
            s in loc for s in ("germany", "deutschland")
        ) or any(
            c in loc
            for c in (
                "berlin",
                "munich",
                "münchen",
                "hamburg",
                "frankfurt",
                "cologne",
                "köln",
                "stuttgart",
                "düsseldorf",
                "leipzig",
                "dresden",
            )
        )

        is_remote = ("remote" in loc) or bool(
            re.search(
                r"\b(fully remote|100%\s*remote|remote-?first|work from anywhere|work from home)\b",
                head,
                re.I,
            )
        )
        is_hybrid = ("hybrid" in loc) or bool(
            re.search(r"\bhybrid\b", title, re.I)
        ) or bool(re.search(r"\bhybrid\b", head[:3000], re.I))

        part_time = bool(
            re.search(r"part\s*[- ]?time|teilzeit|\b50%\b|hours?\s*/\s*week", title, re.I)
        ) or bool(
            re.search(
                r"part\s*[- ]?time|teilzeit|reduced\s+hours|fewer\s+hours", head[:2500], re.I
            )
        )

        software = any(
            w in title or w in head[:2500]
            for w in (
                "software",
                "engineer",
                "engineering",
                "developer",
                "entwickler",
                "programmer",
                "frontend",
                "front-end",
                "backend",
                "back-end",
                "full stack",
                "fullstack",
                "react",
                "vue",
                "angular",
                "mobile",
                "sqa",
                "qa ",
                "devops",
                "cloud",
            )
        )

        # 1 有签证的瑞士软件行业
        if swiss and has_visa and software:
            return 1
        # 2 有签证的德国 remote
        if germany and has_visa and is_remote:
            return 2
        # 3 有签证的德国 hybrid（非纯远程档位已由上一行吃掉）
        if germany and has_visa and is_hybrid and not is_remote:
            return 3
        # 4 远程（全局）
        if is_remote:
            return 4
        # 5 兼职
        if part_time:
            return 5
        return 99

    def apply_priority_meta(self, job: "JobListing") -> None:
        tier = self.compute_priority_tier(job)
        job.priority_tier = tier
        job.priority_label = self._PRIORITY_LABELS.get(tier, "其他")

    def __init__(self, resume_path: str = "resume.json", 
                 gemini_api_key: str = None,
                 model: str = "gemini-2.5-flash",
                 provider: str = "gemini_relay",
                 openai_api_key: str = None,
                 openai_model: str = "gemini-2.5-flash",
                 openai_base_url: str = "",
                 use_llm: bool = True,
                 batch_size: int = 20):
        """
        初始化AI评分器
        
        Args:
            resume_path: 简历JSON文件路径
            model: 使用的模型名称
            use_llm: 是否使用LLM评分，False则使用关键词匹配
            batch_size: 批量评分时每批的岗位数量
        """
        self.resume_path = resume_path
        self.resume = self._load_resume(resume_path)
        self.resume_text = self._format_resume_text()
        
        # Token 使用追踪
        self.token_usage = {
            'input_tokens': 0,
            'output_tokens': 0,
            'total_tokens': 0,
            'api_calls': 0,
            'estimated_cost_usd': 0.0,
        }
        self.token_usage_file = Path(_out_file("token_usage.json"))
        
        # 调试日志：显示LLM配置状态
        requested_provider = (provider or "gemini_relay").strip().lower()
        self.provider = requested_provider
        self.model_name = openai_model or model
        self.openai_model = openai_model or "gemini-2.5-flash"
        raw_base_url = (openai_base_url or "").strip().rstrip("/")
        # 中转网关通常需要 OpenAI 兼容前缀 /v1；若用户只填域名则自动补齐。
        if raw_base_url and not raw_base_url.endswith("/v1"):
            raw_base_url = f"{raw_base_url}/v1"
        self.openai_base_url = raw_base_url
        self.active_model = self.openai_model
        log.info(
            f"AIScorer初始化: use_llm参数={use_llm}, provider={self.provider}, "
            f"gateway=openai-compatible, HAS_OPENAI={HAS_OPENAI}"
        )
        log.info(f"AIScorer初始化: active_model={self.active_model}")
        log.info(f"AIScorer初始化: openai_api_key={'已传入' if openai_api_key else '未传入'}")

        self.use_llm = bool(use_llm)
        self.batch_size = batch_size
        self.openai_client = None

        # 初始化 OpenAI 客户端
        openai_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        if HAS_OPENAI and openai_key:
            client_kwargs = {"api_key": openai_key}
            if self.openai_base_url:
                client_kwargs["base_url"] = self.openai_base_url
            self.openai_client = OpenAI(**client_kwargs)
            log.info(f"已初始化OpenAI客户端，使用模型: {self.openai_model}")

        if self.use_llm:
            if not self.openai_client:
                log.warning("未设置 OPENAI_API_KEY 或未安装 openai，回退关键词匹配")
                self.use_llm = False
        
        if not self.use_llm:
            log.info("使用关键词匹配方式评分")
            self.skills = self._extract_skills()
    
    def _load_resume(self, path: str) -> Dict[str, Any]:
        """加载简历数据"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"加载简历失败: {e}")
            return {}
    
    def _format_resume_text(self) -> str:
        """将简历JSON转换为文本格式供LLM阅读"""
        if not self.resume:
            return "无简历数据"
        
        text_parts = []
        basics = self.resume.get('basics', {})
        
        # 基本信息
        if basics:
            text_parts.append(f"**姓名**: {basics.get('name', 'N/A')}")
            text_parts.append(f"**职位**: {basics.get('headline', 'N/A')}")
            if basics.get('summary'):
                text_parts.append(f"**简介**: {basics.get('summary')}")
        
        sections = self.resume.get('sections', {})
        
        # 工作经验
        exp_section = sections.get('experience', {})
        if exp_section.get('items'):
            text_parts.append("\n**工作经验**:")
            for item in exp_section.get('items', []):
                company = item.get('company', '')
                position = item.get('position', '')
                date = item.get('date', '')
                summary = item.get('summary', '') or ''
                # 移除HTML标签
                summary = re.sub(r'<[^>]+>', ' ', summary).strip()
                text_parts.append(f"- {position} @ {company} ({date})")
                if summary:
                    text_parts.append(f"  {summary[:500]}{'...' if len(summary) > 500 else ''}")
        
        # 技能
        skills_section = sections.get('skills', {})
        if skills_section.get('items'):
            text_parts.append("\n**技能**:")
            for item in skills_section.get('items', []):
                name = item.get('name', '')
                keywords = item.get('keywords', [])
                if name:
                    text_parts.append(f"- {name}: {', '.join(keywords) if keywords else ''}")
        
        # 教育
        edu_section = sections.get('education', {})
        if edu_section.get('items'):
            text_parts.append("\n**教育背景**:")
            for item in edu_section.get('items', []):
                institution = item.get('institution', '')
                area = item.get('area', '')
                degree = item.get('studyType', '')
                text_parts.append(f"- {degree} in {area} @ {institution}")
        
        return "\n".join(text_parts)
    
    def _extract_skills(self) -> set:
        """从简历中提取技能（用于关键词匹配模式）"""
        skills = set()
        sections = self.resume.get('sections', {})
        skills_section = sections.get('skills', {})
        
        for item in skills_section.get('items', []):
            if isinstance(item, dict):
                name = item.get('name', '').lower()
                if name:
                    skills.add(name)
                for kw in item.get('keywords', []):
                    if kw:
                        skills.add(kw.lower())
        
        return skills
    
    def _format_jobs_text(self, jobs: List[JobListing]) -> str:
        """将岗位列表格式化为文本"""
        parts = []
        for job in jobs:
            # 截取JD前1500字符，节省token
            jd_short = job.job_description[:1500] if job.job_description else ""
            parts.append(f"""
---
**Job ID**: {job.job_id}
**职位**: {job.title}
**公司**: {job.company}
**地点**: {job.location}
**描述**: {jd_short}
---""")
        return "\n".join(parts)
    
    def _format_list_jobs_text(self, jobs: List[dict]) -> str:
        """将列表页岗位信息格式化为文本（只有标题和公司）"""
        parts = []
        for job in jobs:
            parts.append(f"- Job ID: {job['job_id']} | 标题: {job['title']} | 公司: {job.get('company', 'Unknown')}")
        return "\n".join(parts)
    
    def _estimate_cost_usd(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """按模型粗略估算本次 token 成本（USD）。"""
        m = (model or "").lower()
        if "gpt-4" in m:
            in_price = self.GPT4_INPUT_PRICE
            out_price = self.GPT4_OUTPUT_PRICE
        else:
            # 默认按 Gemini Flash 估算
            in_price = self.GEMINI_FLASH_INPUT_PRICE
            out_price = self.GEMINI_FLASH_OUTPUT_PRICE
        return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

    def _persist_token_usage(self, input_tokens: int, output_tokens: int, model: str, call_cost: float):
        """将本次调用累计写入 artifacts/token_usage.json（跨运行可追踪）。"""
        data = {
            "api_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "by_model": {},
            "updated_at": "",
        }
        try:
            if self.token_usage_file.exists():
                with open(self.token_usage_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
        except Exception as e:
            log.warning(f"读取 token_usage.json 失败，将重建: {e}")

        data["api_calls"] = int(data.get("api_calls", 0) or 0) + 1
        data["input_tokens"] = int(data.get("input_tokens", 0) or 0) + int(input_tokens)
        data["output_tokens"] = int(data.get("output_tokens", 0) or 0) + int(output_tokens)
        data["total_tokens"] = int(data.get("total_tokens", 0) or 0) + int(input_tokens) + int(output_tokens)
        data["estimated_cost_usd"] = float(data.get("estimated_cost_usd", 0.0) or 0.0) + float(call_cost)

        by_model = data.get("by_model")
        if not isinstance(by_model, dict):
            by_model = {}
        model_key = model or "unknown"
        if model_key not in by_model or not isinstance(by_model.get(model_key), dict):
            by_model[model_key] = {
                "api_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            }
        by_model[model_key]["api_calls"] += 1
        by_model[model_key]["input_tokens"] += int(input_tokens)
        by_model[model_key]["output_tokens"] += int(output_tokens)
        by_model[model_key]["total_tokens"] += int(input_tokens) + int(output_tokens)
        by_model[model_key]["estimated_cost_usd"] += float(call_cost)
        data["by_model"] = by_model
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.token_usage_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_usage_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _track_token_usage(self, input_tokens: int, output_tokens: int, model: str, log_name: str = ""):
        """追踪 Token 使用量
        
        Args:
            input_tokens: 输入 token 数量
            output_tokens: 输出 token 数量
            log_name: 日志标识
        """
        self.token_usage['input_tokens'] += input_tokens
        self.token_usage['output_tokens'] += output_tokens
        self.token_usage['total_tokens'] += input_tokens + output_tokens
        self.token_usage['api_calls'] += 1
        
        total_cost = self._estimate_cost_usd(input_tokens, output_tokens, model)
        self.token_usage['estimated_cost_usd'] += total_cost
        try:
            self._persist_token_usage(input_tokens, output_tokens, model, total_cost)
        except Exception as e:
            log.warning(f"[{log_name}] 写入 token_usage.json 失败: {e}")
        
        log.info(f"[{log_name}] Token使用: +{input_tokens} input, +{output_tokens} output (本次费用: ${total_cost:.5f})")
        log.debug(f"累计Token: {self.token_usage['total_tokens']:,} (API调用: {self.token_usage['api_calls']}次)")
    
    def get_token_usage(self) -> dict:
        """获取 Token 使用统计
        
        Returns:
            dict: 包含 input_tokens, output_tokens, total_tokens, api_calls, estimated_cost_usd
        """
        return {
            **self.token_usage,
            'estimated_cost_usd': round(float(self.token_usage.get('estimated_cost_usd', 0.0) or 0.0), 5)
        }
    
    def _call_openai(self, prompt: str, log_name: str = "OpenAI") -> Optional[List[Dict[str, Any]]]:
        """调用 OpenAI 获取批量评分结果"""
        if not self.openai_client:
            return None
        try:
            log.info(f"[{log_name}] 正在调用OpenAI API...")
            log.info(
                f"[{log_name}] 请求参数: provider={self.provider}, model={self.openai_model}, "
                f"base_url={self.openai_base_url or '(sdk-default)'}, api_key={'set' if self.openai_client else 'missing'}"
            )
            resp = self.openai_client.chat.completions.create(
                model=self.openai_model,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": "You must output valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
            )
            usage = getattr(resp, "usage", None)
            if usage:
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                self._track_token_usage(input_tokens, output_tokens, self.openai_model, log_name)

            # 兼容部分中转网关/SDK返回 str 或 dict，而非标准对象。
            if isinstance(resp, str):
                content = resp.strip()
            elif isinstance(resp, dict):
                choices = resp.get("choices") or []
                first = choices[0] if choices else {}
                message = first.get("message") if isinstance(first, dict) else {}
                content = (message.get("content") if isinstance(message, dict) else "") or ""
                content = content.strip()
            else:
                content = (resp.choices[0].message.content or "").strip()

            content = re.sub(r'^```(?:json)?\s*\n?', '', content)
            content = re.sub(r'\n?```\s*$', '', content)

            def _try_parse_json(text: str):
                text = (text or "").strip()
                if not text:
                    return None
                try:
                    return json.loads(text)
                except Exception:
                    pass

                # 兼容模型在解释文本中夹带 JSON 的情况。
                array_match = re.search(r"\[[\s\S]*\]", text)
                if array_match:
                    try:
                        return json.loads(array_match.group(0))
                    except Exception:
                        pass

                obj_match = re.search(r"\{[\s\S]*\}", text)
                if obj_match:
                    try:
                        return json.loads(obj_match.group(0))
                    except Exception:
                        pass
                return None

            result = _try_parse_json(content)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                # 兼容 {"results":[...]} 这类包装格式
                wrapped = result.get("results") if isinstance(result.get("results"), list) else None
                if wrapped is not None:
                    return wrapped
            return None
        except Exception as e:
            log.error(f"[{log_name}] 调用OpenAI失败: {e}")
            return None
    
    def _fix_truncated_json(self, json_str: str) -> Optional[List[Dict[str, Any]]]:
        """尝试修复被截断的JSON数组"""
        try:
            # 找到最后一个完整的对象
            # 从后往前找 }, 或 }]
            last_complete = json_str.rfind('},')
            if last_complete > 0:
                fixed = json_str[:last_complete + 1] + ']'
                return json.loads(fixed)
            
            # 尝试找最后一个 }
            last_brace = json_str.rfind('}')
            if last_brace > 0:
                fixed = json_str[:last_brace + 1] + ']'
                return json.loads(fixed)
                
        except Exception as e:
            log.debug(f"修复JSON失败: {e}")
        
        # 最后尝试：逐个删除末尾字符直到能解析
        try:
            for i in range(len(json_str), 0, -1):
                test_str = json_str[:i]
                # 找最后一个 }
                last_brace = test_str.rfind('}')
                if last_brace > 0:
                    fixed = test_str[:last_brace + 1] + ']'
                    try:
                        result = json.loads(fixed)
                        if isinstance(result, list) and len(result) > 0:
                            log.debug(f"逐字修复成功，保留 {len(result)} 条")
                            return result
                    except:
                        continue
        except:
            pass
        
        return None
    
    def ai_pre_filter(self, jobs: List[dict], return_all: bool = False) -> List[dict]:
        """
        AI预过滤：根据标题和公司名粗过滤岗位
        
        Args:
            jobs: [{"job_id": "xxx", "title": "xxx", "company": "xxx"}, ...]
            return_all: 如果为True，返回所有岗位并标记过滤状态和原因；否则只返回通过的岗位
        
        Returns:
            如果return_all=True: 所有岗位列表，每个岗位带有 pre_filter_passed 和 pre_filter_reason 字段
            如果return_all=False（默认）: 只返回通过过滤的岗位列表
        """
        log.info("=" * 60)
        log.info(">>> AI粗过滤开始")
        log.info("=" * 60)
        
        if not self.use_llm:
            log.warning("❌ 未启用LLM (use_llm=False)，跳过AI预过滤")
            log.warning("   请检查配置: use_llm_scoring=true 且 OPENAI_API_KEY 已设置")
            for job in jobs:
                job['pre_filter_passed'] = True
                job['pre_filter_reason'] = "LLM未启用，默认通过"
            return jobs
        
        if not jobs:
            log.info("没有岗位需要过滤")
            return []
        
        log.info(f"待过滤岗位数量: {len(jobs)}")
        
        # 打印输入的岗位列表
        log.info("-" * 40)
        log.info("输入岗位列表:")
        for i, job in enumerate(jobs, 1):
            log.info(f"  {i}. [{job['job_id']}] {job['title']} @ {job.get('company', 'Unknown')}")
        log.info("-" * 40)
        
        # 分批处理，每批最多15个岗位，避免输出token不够导致响应截断
        BATCH_SIZE = 15
        MAX_RETRIES = 2  # 结果不完整时的重试次数
        all_passed = []
        all_filtered = []
        total_filtered = 0
        
        for batch_idx in range(0, len(jobs), BATCH_SIZE):
            batch = jobs[batch_idx:batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1
            total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
            
            log.info(f"[批次 {batch_num}/{total_batches}] 处理 {len(batch)} 个岗位...")
            
            jobs_text = self._format_list_jobs_text(batch)
            
            # 使用 ai_pre_filter_prompt.txt 如果存在，否则使用默认 PROMPT
            prompt_template = self.PRE_FILTER_PROMPT
            prompt_file = "ai_pre_filter_prompt.txt"
            
            if os.path.exists(prompt_file):
                try:
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        file_content = f.read().strip()
                        # 只要有 {jobs_text} 占位符就可以使用，{resume_text} 可以是硬编码的
                        if file_content and "{jobs_text}" in file_content:
                            prompt_template = file_content
                            log.info(f"使用来自 {prompt_file} 的自定义 Prompt")
                except Exception as e:
                    log.warning(f"读取自定义 Prompt 失败: {e}, 使用默认 Prompt")

            # 只有当模板中包含 {resume_text} 时才传入参数，否则只传入 jobs_text
            format_args = {"jobs_text": jobs_text}
            if "{resume_text}" in prompt_template:
                format_args["resume_text"] = self.resume_text
                
            prompt = prompt_template.format(**format_args)
            
            # 如果使用默认 Prompt，且文件不存在或内容不同，则保存到文件供调试/修改
            if prompt_template == self.PRE_FILTER_PROMPT and batch_num == 1:
                try:
                    # 为了方便用户修改，保存未格式化的模板（带有占位符）而不只是最终prompt
                    # 这里我们保存最终prompt是为了调试，但为了配置性，最好保存模板
                    # 现阶段为了兼容现有逻辑，我们只写入最终prompt供调试，
                    # 但为了支持用户修改，应该写入模板。鉴于用户提到"此文件作为基准"，
                    # 我们写入默认模板如果文件不存在。
                    if not os.path.exists(prompt_file):
                        with open(prompt_file, 'w', encoding='utf-8') as f:
                            f.write(self.PRE_FILTER_PROMPT)
                        log.info(f"已生成默认 Prompt 模板到 {prompt_file}")
                except:
                    pass
            
            # 保存实际发送的Prompt到 debug_prompt.txt (避免覆盖配置用的 ai_pre_filter_prompt.txt)
            if batch_num == 1:
                try:
                    with open(_out_file("debug_last_prompt.txt"), "w", encoding="utf-8") as f:
                        f.write(prompt)
                except:
                    pass
            
            # 带重试机制的API调用
            results = None
            for retry in range(MAX_RETRIES + 1):
                results = self._call_openai(prompt, log_name=f"AI粗过滤-批次{batch_num}-OpenAI")
                
                if results:
                    # 检查结果完整性：返回的结果数量应该接近批次大小
                    coverage = len(results) / len(batch)
                    if coverage >= 0.8:  # 至少覆盖80%的岗位
                        break
                    elif retry < MAX_RETRIES:
                        log.warning(f"[批次 {batch_num}] 结果不完整 ({len(results)}/{len(batch)}), 重试 {retry + 1}/{MAX_RETRIES}...")
                        import time
                        time.sleep(2)  # 等待2秒后重试
                    else:
                        log.warning(f"[批次 {batch_num}] 重试后结果仍不完整 ({len(results)}/{len(batch)}), 继续处理...")
                elif retry < MAX_RETRIES:
                    log.warning(f"[批次 {batch_num}] AI调用失败, 重试 {retry + 1}/{MAX_RETRIES}...")
                    import time
                    time.sleep(2)
            
            if results:
                log.debug(f"[批次 {batch_num}] 中转AI返回 {len(results)} 条结果")
                
                # 创建job_id到结果的映射
                result_map = {str(r.get('job_id')): r for r in results}
                
                batch_passed = []
                batch_filtered_jobs = []
                batch_filtered = 0
                
                for job in batch:
                    result = result_map.get(job['job_id'])
                    if result:
                        if result.get('keep', True):  # 默认保留
                            job['pre_filter_passed'] = True
                            job['pre_filter_reason'] = result.get('reason', 'AI判定适合')
                            batch_passed.append(job)
                            log.info(f"[已保留] ✅ {job['title']} @ {job.get('company', '')} | {job['pre_filter_reason']}")
                        else:
                            batch_filtered += 1
                            reason = (result.get('reason') or '不符合初筛规则').strip()
                            # keep:false 时 reason 必须写清「为何不继续」；模型偶发会写成匹配说明，统一加前缀便于识别
                            if not reason.startswith("未通过初筛"):
                                reason = f"未通过初筛：{reason}"
                            job['pre_filter_passed'] = False
                            job['pre_filter_reason'] = reason
                            batch_filtered_jobs.append(job)
                            log.info(f"[已过滤] ❌ {job['title']} @ {job.get('company', '')} | {reason}")
                    else:
                        # 如果AI没返回结果，默认保留
                        job['pre_filter_passed'] = True
                        job['pre_filter_reason'] = "AI未返回结果，默认保留"
                        batch_passed.append(job)
                
                all_passed.extend(batch_passed)
                all_filtered.extend(batch_filtered_jobs)
                total_filtered += batch_filtered
                log.info(f"[批次 {batch_num}] 保留: {len(batch_passed)}, 过滤: {batch_filtered}")
            else:
                # 批次调用失败，保留该批次所有岗位
                log.warning(f"[批次 {batch_num}] AI调用失败，保留该批次所有岗位")
                for job in batch:
                    job['pre_filter_passed'] = True
                    job['pre_filter_reason'] = "AI调用失败，默认通过"
                all_passed.extend(batch)
        
        log.info("=" * 60)
        log.info(f"AI粗过滤结果汇总:")
        log.info(f"  输入: {len(jobs)} 个岗位")
        log.info(f"  保留: {len(all_passed)} 个")
        log.info(f"  过滤: {total_filtered} 个")
        log.info("=" * 60)
        
        # 打印保留的岗位
        if all_passed:
            log.info("保留的岗位:")
            for i, job in enumerate(all_passed, 1):
                log.info(f"  ✓ {i}. {job['title']} @ {job.get('company', '')}")
        
        if return_all:
            # 返回所有岗位（通过的在前，被过滤的在后）
            return all_passed + all_filtered
        else:
            return all_passed
    
    def score_jobs_batch(self, jobs: List[JobListing]) -> List[JobListing]:
        """使用中转 AI 批量评分"""
        jobs_text = self._format_jobs_text(jobs)
        prompt = self.BATCH_SCORING_PROMPT.format(
            resume_text=self.resume_text,
            jobs_text=jobs_text
        )
        
        results = self._call_openai(prompt, log_name="OpenAI")
        
        if results:
            # 创建job_id到结果的映射
            result_map = {str(r.get('job_id')): r for r in results}
            
            for job in jobs:
                result = result_map.get(job.job_id)
                if result:
                    score = float(result.get('score', 50))
                    job.ai_score = score
                    
                    # 构建评分原因
                    reason = str(result.get('reason', '') or '').strip()
                    matched = result.get('matched_skills', [])
                    missing = result.get('missing_skills', [])

                    # 兜底：避免出现低分但没有明确原因
                    if not reason:
                        if score < 60:
                            if missing:
                                reason = f"低分原因：关键能力缺口（{', '.join(missing[:2])}）"
                            else:
                                reason = "低分原因：与岗位核心要求匹配度不足"
                        else:
                            reason = "模型未返回具体原因"
                    
                    reason_parts = [reason] if reason else []
                    if matched:
                        reason_parts.append(f"✓{','.join(matched[:3])}")
                    if missing:
                        reason_parts.append(f"✗{','.join(missing[:2])}")
                    
                    job.ai_reason = " | ".join(reason_parts)
                else:
                    job.ai_score = 50.0
                    job.ai_reason = "未获取到评分"
            
            log.info(f"批量评分完成: {len(jobs)} 个岗位")
        else:
            # Gemini调用失败，设置默认分数
            for job in jobs:
                job.ai_score = 50.0
                job.ai_reason = "LLM评分失败"
        
        return jobs
    
    def score_job_with_keywords(self, job: JobListing) -> JobListing:
        """使用关键词匹配为岗位评分（备用方案）"""
        if not self.resume:
            job.ai_score = 50.0
            job.ai_reason = "无简历数据"
            return job
        
        jd_lower = job.job_description.lower()
        matched = []
        
        for skill in self.skills:
            if len(skill) > 2 and skill in jd_lower:
                matched.append(skill)
        
        # 简单计算分数
        score = min(len(matched) * 5 + 30, 100)
        job.ai_score = float(score)
        job.ai_reason = f"关键词匹配: {', '.join(matched[:5])}" if matched else "无明显匹配"
        
        return job
    
    def score_jobs(self, jobs: List[JobListing], delay: float = 1.0) -> List[JobListing]:
        """为岗位列表打分并排序
        
        Args:
            jobs: 岗位列表
            delay: 批次间隔（秒），避免限流
        """
        if not jobs:
            return []
        
        if self.use_llm:
            # 批量评分模式
            scored_jobs = []
            total_batches = (len(jobs) + self.batch_size - 1) // self.batch_size
            
            for i in range(0, len(jobs), self.batch_size):
                batch = jobs[i:i + self.batch_size]
                batch_num = i // self.batch_size + 1
                log.info(f"正在批量评分 ({batch_num}/{total_batches}): {len(batch)} 个岗位")
                
                scored_batch = self.score_jobs_batch(batch)
                scored_jobs.extend(scored_batch)
                
                # 批次间添加延迟
                if batch_num < total_batches:
                    time.sleep(delay)
        else:
            # 关键词匹配模式
            scored_jobs = []
            for job in jobs:
                scored_jobs.append(self.score_job_with_keywords(job))
        
        for job in scored_jobs:
            self.apply_priority_meta(job)
        # 优先级档位越小越靠前；同档内按 AI / 关键词分数从高到低
        scored_jobs.sort(key=lambda x: (x.priority_tier, -x.ai_score))
        return scored_jobs


def save_jobs_to_csv(jobs: List[JobListing], filename: str = "scraped_jobs.csv") -> None:
    """保存岗位到CSV文件"""
    if not (filename or "").strip():
        log.info("未配置 CSV 路径，跳过写出")
        return
    if not jobs:
        log.warning("没有岗位可保存")
        return
    
    fieldnames = [
        'job_id', 'title', 'company', 'location', 'url', 
        'is_easy_apply', 'experience_years', 'is_english',
        'passed_filter', 'priority_tier', 'priority_label', 'ai_score', 'ai_reason',
        'posted_time', 'applicants', 'job_description'
    ]
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            row = asdict(job)
            # 只写入指定的字段
            row = {k: v for k, v in row.items() if k in fieldnames}
            writer.writerow(row)
    
    log.info(f"已保存 {len(jobs)} 个岗位到 {filename}")


def save_jobs_to_json(jobs: List[JobListing], filename: str = "scraped_jobs.json") -> None:
    """保存岗位到JSON文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump([asdict(job) for job in jobs], f, ensure_ascii=False, indent=2)
    log.info(f"已保存 {len(jobs)} 个岗位到 {filename}")


def merge_jobs_progress_after_filter_and_score(
    passed_scored: List[JobListing],
    filtered_out: List[JobListing],
    progress_path: str = None,
) -> None:
    """将「关键词/德语/年限过滤 + LLM 评分」后的结果合并回 jobs_progress.json。

    爬取过程中 _save_progress 写入的岗位默认 passed_filter=False，但 ai_reason 可能已是
    [AI初筛] 匹配说明，会与真实过滤状态错位。本函数按 job_id 覆盖本次运行涉及的记录，
    并保留已存在条目的 status、resume_path 等终态字段。
    """
    path = progress_path or _out_file("jobs_progress.json")
    existing: List[dict] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                existing = raw
        except Exception as e:
            log.warning(f"读取 jobs_progress 合并前失败，将重建: {e}")
            existing = []

    preserve_status = {
        "applied",
        "closed",
        "failed",
        "skipped",
        "resume_ready",
        "resume_generated",  # 历史别名
    }
    by_id: Dict[str, dict] = {}
    for row in existing:
        jid = str(row.get("job_id") or "")
        if jid:
            by_id[jid] = dict(row)

    def upsert(job: JobListing, row: dict) -> None:
        jid = str(job.job_id or "")
        if not jid:
            return
        old = by_id.get(jid, {})
        merged = {**old, **row}
        st = (old.get("status") or "").strip().lower()
        if st in preserve_status:
            merged["status"] = old.get("status")
        if old.get("resume_path") and not row.get("resume_path"):
            merged["resume_path"] = old.get("resume_path")
        by_id[jid] = merged

    for job in passed_scored:
        upsert(job, asdict(job))
    for job in filtered_out:
        upsert(job, asdict(job))

    # 稳定顺序：高分在前，便于人工浏览
    out = sorted(by_id.values(), key=lambda r: float(r.get("ai_score", 0) or 0), reverse=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        log.info(
            f"已合并过滤/评分结果到 jobs_progress.json: 更新 {len(passed_scored) + len(filtered_out)} 条相关岗位"
        )
    except Exception as e:
        log.error(f"合并写入 jobs_progress.json 失败: {e}")


def main():
    """主函数"""
    # 加载配置
    base_dir = Path(__file__).parent
    config_file = base_dir / "scraper_config.yaml"
    if not config_file.exists():
        config_file = base_dir / "config.yaml"
    
    log.info(f"加载配置文件: {config_file}")
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    username = config.get('username')
    password = config.get('password')
    positions = config.get('positions', ['Software Engineer'])
    locations = config.get('locations', ['Germany'])
    experience_levels = config.get('experience_level', [1, 2, 3])  # Entry, Associate, Mid-Senior
    max_pages = config.get('max_pages', 3)
    max_experience_years = config.get('max_experience_years', 5)
    min_experience_years = config.get('min_experience_years', 0)
    filter_german_jobs = config.get('filter_german_jobs', True)
    headless = config.get('headless', False)
    resume_path = config.get('resume_path', 'resume.json')
    
    # 预过滤配置
    enable_pre_filter = config.get('enable_pre_filter', True)
    enable_ai_pre_filter = config.get('enable_ai_pre_filter', True)
    pages_before_detail = config.get('pages_before_detail', 3)
    exclude_title_keywords = config.get('exclude_title_keywords', [])
    german_title_keywords = config.get('german_title_keywords', [])
    
    # AI评分配置
    ai_provider = (config.get('ai_provider') or 'gemini_relay')
    use_llm_scoring = config.get('use_llm_scoring', True)
    gemini_api_key = ""
    gemini_model = config.get('openai_model', 'gemini-2.5-flash')
    openai_api_key = config.get('openai_api_key') or os.environ.get('OPENAI_API_KEY')
    openai_model = config.get('openai_model', 'gemini-2.5-flash')
    openai_base_url = (
        config.get('openai_base_url')
        or config.get('server_url')
        or os.environ.get('AI_SERVER_URL', '')
        or os.environ.get('OPENAI_BASE_URL', '')
    )
    batch_size = config.get('batch_size', 20)
    llm_delay = config.get('llm_delay', 1.0)
    effective_model = openai_model
    
    # 输出文件配置
    save_csv = bool(config.get('save_csv', False))
    output_passed_csv = (config.get('output_passed_csv') or '').strip() or (
        str(_out_file('jobs_passed.csv')) if save_csv else ''
    )
    output_filtered_csv = (config.get('output_filtered_csv') or '').strip() or (
        str(_out_file('jobs_filtered_out.csv')) if save_csv else ''
    )
    output_json = config.get('output_json', _out_file('jobs_passed.json'))
    
    # 新增的URL参数
    geo_id = config.get('geo_id')
    time_filter = config.get('time_filter')
    distance = config.get('distance')
    sort_by = config.get('sort_by', 'DD')
    
    # 分页续爬配置
    start_page = config.get('start_page', 0)  # 从第几页开始 (0-indexed)
    auto_resume = config.get('auto_resume', True)  # 是否自动从上次进度继续
    list_only = config.get('list_only', False)  # 是否只爬列表不进详情页
    
    # 验证配置
    if (username == '<your_email>' or password == '<your_password>') and not os.path.exists('linkedin_cookies.json'):
        log.warning("未配置登录信息，将打开浏览器让你手动登录...")
        # 设置为空字符串，触发手动登录流程
        username = ""
        password = ""
    
    log.info("=" * 50)
    log.info("LinkedIn 岗位爬取系统")
    log.info("=" * 50)
    log.info(f"搜索职位: {positions}")
    log.info(f"搜索地点: {locations}")
    log.info(f"经验级别: {experience_levels}")
    log.info(f"最大页数: {max_pages}")
    log.info(f"经验要求: {min_experience_years}-{max_experience_years}年")
    log.info(f"德语JD过滤: {'启用' if filter_german_jobs else '禁用'}")
    log.info(f"关键词预过滤: {'启用' if enable_pre_filter else '禁用'}")
    log.info(f"AI预过滤: {'启用' if enable_ai_pre_filter else '禁用'}")
    if enable_ai_pre_filter:
        log.info(f"攒 {pages_before_detail} 页后进行AI筛选")
    log.info(f"LLM评分: {'启用' if use_llm_scoring else '禁用'} (provider={ai_provider}, HAS_OPENAI={HAS_OPENAI})")
    log.info(f"当前生效模型: {effective_model}")
    log.info("Gemini通道: 已启用（通过 OpenAI 兼容中转）")
    log.info(f"OpenAI模型: {openai_model}")
    log.info(f"OpenAI API Key: {'已设置' if openai_api_key else '未设置'}")
    log.info(f"起始页: {start_page + 1} (auto_resume={auto_resume})")
    log.info(f"只爬列表: {'是' if list_only else '否'}")
    log.info(f"写出岗位 CSV: {'是' if save_csv else '否'} (save_csv)")
    log.info("=" * 50)
    
    # 创建爬取器
    scraper = LinkedInScraper(username, password, headless=headless)
    scraper.write_job_csv = save_csv
    
    # 如果配置了自定义预过滤关键词，更新类属性
    if exclude_title_keywords:
        scraper.EXCLUDE_TITLE_KEYWORDS = [kw.lower() for kw in exclude_title_keywords]
    if german_title_keywords:
        scraper.GERMAN_TITLE_KEYWORDS = [kw.lower() for kw in german_title_keywords]
    
    all_jobs = []  # 在 try 外部初始化，确保 except/finally 中可访问
    ai_scorer = None  # AI评分器
    progress_mgr = JobProgressManager()  # 进度管理器
    
    try:
        # 启动浏览器并登录
        scraper.start_browser()
        
        if not scraper.login():
            log.error("登录失败，程序退出")
            return
        
        # 如果启用AI预过滤，先创建AI评分器
        if enable_ai_pre_filter:
            ai_scorer = AIScorer(
                resume_path=resume_path,
                gemini_api_key=gemini_api_key,
                model=gemini_model,
                provider=ai_provider,
                openai_api_key=openai_api_key,
                openai_model=openai_model,
                openai_base_url=openai_base_url,
                use_llm=use_llm_scoring,
                batch_size=batch_size
            )
        
        # 爬取岗位
        for position in positions:
            for location in locations:
                log.info(f"\n>>> 搜索: {position} @ {location}")
                
                # 计算起始页：如果 auto_resume 则从上次进度继续，否则用配置的 start_page
                actual_start_page = start_page
                if auto_resume:
                    last_page = LinkedInScraper.get_crawl_progress(position, location, sort_by=sort_by)
                    if last_page > 0:
                        actual_start_page = last_page + 1  # 从上次的下一页继续
                        log.info(f"[续爬] 检测到上次爬到第 {last_page + 1} 页，从第 {actual_start_page + 1} 页继续")
                
                jobs = scraper.scrape_jobs(
                    position=position,
                    location=location,
                    max_pages=max_pages,
                    experience_levels=None,  # 不过滤经验级别
                    geo_id=geo_id,
                    time_filter=time_filter,
                    distance=distance,
                    sort_by=sort_by,
                    pre_filter=enable_pre_filter,  # 关键词预过滤
                    ai_pre_filter=enable_ai_pre_filter,  # AI预过滤
                    ai_scorer=ai_scorer,  # AI评分器
                    pages_before_detail=pages_before_detail,  # 攒多少页
                    start_page=actual_start_page,  # 起始页
                    list_only=list_only,  # 是否只爬列表
                    progress_manager=progress_mgr  # 进度管理器
                )
                all_jobs.extend(jobs)
                log.info(f"本次搜索获取 {len(jobs)} 个岗位")
        
        # 去重
        seen_ids = set()
        unique_jobs = []
        for job in all_jobs:
            if job.job_id not in seen_ids:
                seen_ids.add(job.job_id)
                unique_jobs.append(job)
        
        log.info(f"\n共爬取 {len(all_jobs)} 个岗位，去重后 {len(unique_jobs)} 个")
        
        # 过滤岗位
        log.info("\n>>> 开始过滤岗位...")
        job_filter = JobFilter(
            max_experience_years=max_experience_years,
            min_experience_years=min_experience_years,
            reject_german_jd=filter_german_jobs,
        )
        passed_jobs, filtered_jobs = job_filter.filter_jobs(unique_jobs)
        
        # AI评分
        log.info("\n>>> 开始AI评分...")
        scorer = AIScorer(
            resume_path=resume_path,
            gemini_api_key=gemini_api_key,
            model=gemini_model,
            provider=ai_provider,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            openai_base_url=openai_base_url,
            use_llm=use_llm_scoring,
            batch_size=batch_size
        )
        scored_jobs = scorer.score_jobs(passed_jobs, delay=llm_delay)
        
        # 分类：Easy Apply vs 非Easy Apply
        easy_apply_jobs = [j for j in scored_jobs if j.is_easy_apply]
        manual_apply_jobs = [j for j in scored_jobs if not j.is_easy_apply]
        
        log.info("\n" + "=" * 50)
        log.info("爬取结果汇总")
        log.info("=" * 50)
        log.info(f"总爬取数量: {len(unique_jobs)}")
        log.info(f"通过过滤: {len(passed_jobs)}")
        log.info(f"被过滤: {len(filtered_jobs)}")
        log.info(f"  - Easy Apply: {len(easy_apply_jobs)}")
        log.info(f"  - 手动投递: {len(manual_apply_jobs)}")
        
        # 保存结果（CSV 由 output.save_csv / scraper_config.save_csv 控制）
        if save_csv:
            if output_passed_csv:
                save_jobs_to_csv(scored_jobs, output_passed_csv)
            if output_filtered_csv:
                save_jobs_to_csv(filtered_jobs, output_filtered_csv)
        else:
            log.info("已按配置 save_csv=false，跳过 jobs_passed.csv / jobs_filtered_out.csv")
        save_jobs_to_json(scored_jobs, output_json)

        # 与增量爬取写入的 jobs_progress 对齐：修正 passed_filter / ai_reason 与过滤、评分一致
        merge_jobs_progress_after_filter_and_score(
            passed_scored=scored_jobs,
            filtered_out=filtered_jobs,
            progress_path=str(_out_file("jobs_progress.json")),
        )
        
        # 打印推荐岗位
        print("\n" + "=" * 60)
        print("🎯 推荐岗位 TOP 10 (先按投递优先级分档，再按匹配分排序)")
        print("=" * 60)
        
        for i, job in enumerate(scored_jobs[:10], 1):
            easy_tag = "✅ Easy Apply" if job.is_easy_apply else "📝 手动投递"
            pri = getattr(job, "priority_label", "") or f"P{getattr(job, 'priority_tier', 99)}"
            print(f"\n{i}. [{pri}] [{job.ai_score:.1f}分] {job.title}")
            print(f"   🏢 {job.company}")
            print(f"   📍 {job.location}")
            print(f"   {easy_tag}")
            print(f"   🔗 {job.url}")
            if job.ai_reason:
                print(f"   💡 {job.ai_reason}")
        
        print("\n" + "=" * 60)
        print("结果已保存到:")
        if save_csv and output_passed_csv:
            print(f"  - 通过的岗位(CSV): {output_passed_csv}")
        if save_csv and output_filtered_csv:
            print(f"  - 被过滤岗位(CSV): {output_filtered_csv}")
        print(f"  - JSON: {output_json}")
        print("=" * 60)
        
    except KeyboardInterrupt:
        log.info("\n用户中断，正在退出...")
        # 保存已爬取的结果
        if all_jobs:
            log.info(f"正在保存 {len(all_jobs)} 个已爬取的岗位...")
            scraper._save_progress(all_jobs)
    except Exception as e:
        log.error(f"运行出错: {e}")
        # 保存已爬取的结果
        if all_jobs:
            log.info(f"正在保存 {len(all_jobs)} 个已爬取的岗位...")
            scraper._save_progress(all_jobs)
    finally:
        # 最终保存（确保任何情况都保存）
        if all_jobs:
            scraper._save_progress(all_jobs)
        scraper.close()


if __name__ == '__main__':
    main()
