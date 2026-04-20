"""
LinkedIn Easy Apply 浏览器自动化：打开职位页、点击 Easy Apply、在向导中填写；
可选仅填表不提交（保留在提交前一步，多标签页并排，便于手动点 Submit）。

依赖与 linkedin_scraper 相同的 Selenium 环境；选择器随 LinkedIn 改版可能需调整。
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin
from typing import Any, Optional

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)

# 与 auto_apply.linkedin_source.contact_by_country("switzerland") 默认一致（todo 缺省时）
_SWISS_DEFAULT_PHONE = "+41 799067274"
_SWISS_DEFAULT_ADDRESS = "Unterfuehrungsstrasse 25 4600 Olten"


def _resolve_path(p: str, bases: list[Path]) -> Optional[Path]:
    raw = (p or "").strip()
    if not raw:
        return None
    cand = Path(raw).expanduser()
    if cand.is_file():
        return cand.resolve()
    for b in bases:
        c = (b / raw).resolve()
        if c.is_file():
            return c
    return None


def _safe_click(driver: WebDriver, el) -> None:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.2)
        driver.execute_script("arguments[0].click();", el)
    except Exception:
        el.click()


def _modal_rect_substantial(el) -> bool:
    """排除占位/零尺寸的「假」节点。"""
    try:
        r = el.rect
        return int(r.get("width", 0) or 0) >= 120 and int(r.get("height", 0) or 0) >= 80
    except Exception:
        return True


def _modal_contains_easy_apply_markers(container) -> bool:
    """在泛型 dialog / artdeco-modal 上判断是否像 Easy Apply 向导（避免点到其它弹窗）。"""
    try:
        cls = (container.get_attribute("class") or "").lower()
        if "jobs-easy-apply" in cls or "easy-apply" in cls:
            return True
    except Exception:
        return False
    markers = (
        "input[type='file']",
        ".jobs-easy-apply-footer",
        "footer.jobs-easy-apply-footer",
        ".jobs-easy-apply-footer__info",
        ".fb-dash-form-element",
        "[data-test-form-element]",
        "button[data-easy-apply-next-button]",
        "[class*='jobs-easy-apply-form']",
        ".jobs-easy-apply-form-section",
        "#jobs-apply-header",
    )
    for sel in markers:
        try:
            if container.find_elements(By.CSS_SELECTOR, sel):
                return True
        except Exception:
            continue
    return False


def _modal_root(driver: WebDriver):
    """
    LinkedIn 改版后弹层可能仍是 artdeco-modal，但不再带 jobs-easy-apply-modal 等旧 class；
    仅用 role=dialog 又会误中其它弹窗。这里先精确、再按「申请表单特征」在泛型 modal 里挑最大可见层。
    """
    specific_selectors = [
        # 与当前 prod DOM 一致：外层 dialog + jobs-easy-apply-modal
        "div.artdeco-modal.jobs-easy-apply-modal[role='dialog']",
        "div.jobs-easy-apply-modal[role='dialog']",
        "div.jobs-easy-apply-modal__content",
        "div[data-test-modal-container]",
        "div.artdeco-modal.jobs-easy-apply-modal",
        ".jobs-easy-apply-modal div.artdeco-modal__content",
        "div.jobs-easy-apply-modal__form",
        "[class*='jobs-easy-apply-modal'] div.artdeco-modal__content",
    ]
    for sel in specific_selectors:
        try:
            for e in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if e.is_displayed() and _modal_rect_substantial(e):
                        return e
                except StaleElementReferenceException:
                    continue
        except Exception:
            continue

    broad_selectors = (
        "div[role='dialog']",
        "aside[role='dialog']",
        "dialog[open]",
        "dialog",
        "div.artdeco-modal",
        "div[data-test-modal]",
        "[aria-modal='true']",
    )
    best = None
    best_area = 0
    for sel in broad_selectors:
        try:
            for e in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if not e.is_displayed() or not _modal_rect_substantial(e):
                        continue
                    if not _modal_contains_easy_apply_markers(e):
                        continue
                    r = e.rect
                    area = int(r.get("width", 0) or 0) * int(r.get("height", 0) or 0)
                    if area >= best_area:
                        best = e
                        best_area = area
                except StaleElementReferenceException:
                    continue
        except Exception:
            continue
    if best is not None:
        return best

    try:
        for e in driver.find_elements(By.CSS_SELECTOR, "[class*='jobs-easy-apply']"):
            try:
                if e.is_displayed() and _modal_rect_substantial(e):
                    return e
            except StaleElementReferenceException:
                continue
    except Exception:
        pass

    return None


def _page_is_apply_route(driver: WebDriver) -> bool:
    u = (driver.current_url or "").lower()
    if "linkedin.com" not in u:
        return False
    return "/apply/" in u or "opensduiapplyflow" in u


def _page_apply_shell(driver: WebDriver):
    """
    点击带 openSDUIApplyFlow 的链接后，常整页进入 .../jobs/view/<id>/apply/...，
    此时 DOM 里可能没有 role=dialog / .artdeco-modal，只在 main 里画申请表。
    """
    for sel in (
        "div.jobs-easy-apply-modal__content",
        ".jobs-apply-form",
        "main",
        "[role='main']",
    ):
        for e in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if not e.is_displayed():
                    continue
                if _modal_contains_easy_apply_markers(e):
                    return e
                if e.find_elements(By.CSS_SELECTOR, "#jobs-apply-header") or e.find_elements(
                    By.CSS_SELECTOR, "button[data-easy-apply-next-button]"
                ):
                    return e
            except Exception:
                continue
    return None


def _inline_apply_shell(driver: WebDriver):
    """同一职位 URL 下内联渲染的向导（无弹层、无 /apply/ 路由）。"""
    try:
        has_hdr = any(
            e.is_displayed()
            for e in driver.find_elements(By.CSS_SELECTOR, "#jobs-apply-header, h2#jobs-apply-header")
        )
        has_next = any(
            e.is_displayed()
            for e in driver.find_elements(By.CSS_SELECTOR, "button[data-easy-apply-next-button]")
        )
        if not (has_hdr or has_next):
            return None
        for sel in ("div.jobs-easy-apply-modal__content", "main", "[role='main']"):
            for e in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if e.is_displayed() and _modal_contains_easy_apply_markers(e):
                        return e
                except Exception:
                    continue
        for m in driver.find_elements(By.CSS_SELECTOR, "main, [role='main']"):
            try:
                if not m.is_displayed():
                    continue
                if m.find_elements(By.CSS_SELECTOR, ".fb-dash-form-element, [data-test-form-element]"):
                    return m
            except Exception:
                continue
    except Exception:
        pass
    return None


def _apply_wizard_root(driver: WebDriver):
    """弹层 modal 或整页 /apply/ 或内联向导，统一取填表根节点。"""
    r = _modal_root(driver)
    if r is not None:
        return r
    if _page_is_apply_route(driver):
        r = _page_apply_shell(driver)
        if r is not None:
            return r
    return _inline_apply_shell(driver)


class EasyApplyAutomation:
    _CLOSED_JOB_MARKERS = (
        "no longer accepting applications",
        "is no longer accepting applications",
        "no longer accepting",
        "this job is closed",
        "job is closed",
        "bewerbungen werden nicht mehr angenommen",
        "nimmt keine bewerbungen mehr",
    )

    def __init__(self, driver: WebDriver, default_wait_s: int = 22) -> None:
        self.driver = driver
        self.default_wait_s = default_wait_s
        self.closed_job_ids: list[str] = []
        self._closed_job_set: set[str] = set()
        self.no_easy_apply_job_ids: list[str] = []
        self._no_easy_apply_set: set[str] = set()

    def _wait(self, seconds: Optional[float] = None) -> WebDriverWait:
        return WebDriverWait(self.driver, int(seconds or self.default_wait_s))

    def apply_one(
        self,
        job_row: dict[str, Any],
        artifacts_base: Path,
        *,
        submit_application: bool = True,
        open_in_new_tab: bool = False,
    ) -> bool:
        """打开 job_row['url']，走 Easy Apply 向导填表；submit_application=False 时在提交前停住并成功返回。"""
        url = (job_row.get("url") or "").strip()
        job_id = str(job_row.get("job_id") or "")
        if not url:
            log.error("apply_one: 缺少 url")
            return False

        resume_path = _resolve_path(
            str(job_row.get("resume_path") or ""),
            [artifacts_base, Path.cwd(), artifacts_base.parent],
        )
        if not resume_path or not resume_path.is_file():
            log.error("apply_one: 找不到简历 PDF: %s", job_row.get("resume_path"))
            return False

        answers: dict[str, Any] = {}
        raw_ans = job_row.get("easy_apply_answers")
        if isinstance(raw_ans, dict):
            answers = raw_ans
        else:
            ans_file = artifacts_base / "easy_apply_answers" / f"{job_id}.json"
            if ans_file.is_file():
                import json

                bundle = json.loads(ans_file.read_text(encoding="utf-8"))
                if isinstance(bundle.get("answers"), dict):
                    answers = bundle["answers"]

        log.info("Easy Apply 浏览器: 打开 %s", url[:80])
        if open_in_new_tab:
            self.driver.execute_script("window.open(arguments[0], '_blank');", url)
            self.driver.switch_to.window(self.driver.window_handles[-1])
        else:
            self.driver.get(url)
        time.sleep(0.45)
        if self._handle_closed_job_if_any(job_id, open_in_new_tab, "打开页面后"):
            return False
        time.sleep(0.75)
        if self._handle_closed_job_if_any(job_id, open_in_new_tab, "等待前"):
            return False
        self._wait_for_job_apply_area()

        if self._handle_closed_job_if_any(job_id, open_in_new_tab, "职位区加载后"):
            return False

        clicked = False
        for attempt in range(3):
            if self._handle_closed_job_if_any(job_id, open_in_new_tab, f"第 {attempt + 1}/3 次点 Easy Apply 前"):
                return False
            if self._click_easy_apply_button():
                clicked = True
                break
            log.warning(
                "未找到 Easy Apply（第 %s/3 次），1s 后重试（页面可能仍在渲染）",
                attempt + 1,
            )
            time.sleep(1.0)
        if not clicked:
            if job_id and job_id not in self._no_easy_apply_set:
                self._no_easy_apply_set.add(job_id)
                self.no_easy_apply_job_ids.append(job_id)
            log.warning("未找到可点击的 Easy Apply 按钮，按已投递处理: job_id=%s", job_id)
            self._close_tab_if_opened_for_this_job(open_in_new_tab)
            return False

        time.sleep(0.6)
        ready, closed = self._wait_for_apply_wizard_ready(job_id, open_in_new_tab)
        if closed:
            return False
        if not ready:
            try:
                cur = self.driver.current_url
                nd = len(self.driver.find_elements(By.CSS_SELECTOR, "[role='dialog']"))
                nm = len(self.driver.find_elements(By.CSS_SELECTOR, ".artdeco-modal"))
                nf = len(self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']"))
                nfe = len(self.driver.find_elements(By.CSS_SELECTOR, "[data-test-form-element]"))
                nh = len(self.driver.find_elements(By.CSS_SELECTOR, "#jobs-apply-header"))
                nn = len(self.driver.find_elements(By.CSS_SELECTOR, "button[data-easy-apply-next-button]"))
            except Exception:
                cur = "?"
                nd = nm = nf = nfe = nh = nn = -1
            log.error(
                "Easy Apply 向导检测超时: job_id=%s current_url=%s "
                "role=dialog=%s artdeco-modal=%s file_input=%s "
                "data-test-form-element=%s jobs-apply-header=%s easy-apply-next=%s",
                job_id,
                cur,
                nd,
                nm,
                nf,
                nfe,
                nh,
                nn,
            )
            return False

        for step in range(22):
            root = _apply_wizard_root(self.driver)
            if root is None:
                if self._handle_closed_job_if_any(job_id, open_in_new_tab, "填表步骤中"):
                    return False
                if self._looks_submitted():
                    log.info("弹窗已关闭且页面显示已投递迹象: job_id=%s", job_id)
                    return True
                time.sleep(0.6)
                continue

            try:
                self._upload_resume_if_present(root, str(resume_path))
                self._fill_text_fields(root, answers, job_row)
                self._fill_selects(root, answers, job_row)
                self._answer_yes_no_radios(root)
            except StaleElementReferenceException:
                time.sleep(0.5)
                continue

            if self._submit_button_visible():
                time.sleep(1.0)
                if not submit_application:
                    log.info("已填至提交页，未点击提交（保留本页待手动提交）: job_id=%s", job_id)
                    return True
                if self._click_submit():
                    if self._wait_post_submit():
                        log.info("已提交申请: job_id=%s", job_id)
                        return True
                    log.warning("点击提交后未确认成功，可能需人工检查: job_id=%s", job_id)
                    return False

            if not self._click_next():
                if self._submit_button_visible() and not submit_application:
                    log.info("已填至提交页，未点击提交: job_id=%s", job_id)
                    return True
                log.warning("未找到下一步/提交按钮，可能卡在某步: job_id=%s step=%s", job_id, step)
                return False
            time.sleep(0.85)

        log.error("超过最大步数仍未完成: job_id=%s", job_id)
        return False

    _EASY_APPLY_LABEL = re.compile(r"easy\s*apply", re.IGNORECASE)

    def _label_says_easy_apply(self, el) -> bool:
        """用可见文案 + aria-label 等判断是否为 Easy Apply（排除仅「Apply」外链）。"""
        parts = [
            el.text or "",
            el.get_attribute("aria-label") or "",
            el.get_attribute("title") or "",
            el.get_attribute("data-control-name") or "",
        ]
        blob = " ".join(p for p in parts if p)
        return bool(blob and self._EASY_APPLY_LABEL.search(blob))

    def _wait_for_job_apply_area(self) -> None:
        """等职位详情区出现；每个选择器单独短等，避免旧逻辑「多个 18s 串行」拖到一分钟以上。"""
        hints = [
            (By.CSS_SELECTOR, ".jobs-details-top-card"),
            (By.CSS_SELECTOR, ".jobs-search-job-details__body"),
            (By.CSS_SELECTOR, ".jobs-unified-top-card"),
            (By.CSS_SELECTOR, "[class*='jobs-apply']"),
            (By.CSS_SELECTOR, "main"),
        ]
        per_hint_s = 4
        for by, sel in hints:
            try:
                self._wait(per_hint_s).until(EC.presence_of_element_located((by, sel)))
                return
            except TimeoutException:
                continue

    def _job_closed_banner_visible(self) -> bool:
        """优先：LinkedIn 行内/Toast 提示（含 aria-live、Error 图标），不必等整页 HTML 稳定。"""
        xps = (
            "//p[contains(.,'No longer accepting applications')]",
            "//*[contains(.,'No longer accepting applications')][@aria-live='assertive' or @aria-live='polite']",
            "//*[@aria-live='assertive' or @aria-live='polite'][.//*[contains(.,'No longer accepting applications')]]",
        )
        for xp in xps:
            try:
                for el in self.driver.find_elements(By.XPATH, xp):
                    try:
                        if el.is_displayed() and "accepting" in (el.text or "").lower():
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, "[aria-live='assertive'], [aria-live='polite']"):
                try:
                    if not el.is_displayed():
                        continue
                    t = (el.text or "").lower()
                    if "no longer accepting applications" in t or (
                        "no longer accepting" in t and "application" in t
                    ):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _job_no_longer_accepting_applications(self) -> bool:
        if self._job_closed_banner_visible():
            return True
        low = (self.driver.page_source or "").lower()
        return any(m in low for m in self._CLOSED_JOB_MARKERS)

    def _handle_closed_job_if_any(self, job_id: str, open_in_new_tab: bool, phase: str) -> bool:
        """若岗位已关闭：打日志、关标签（若适用）、返回 True 表示应结束本岗位。"""
        if not self._job_no_longer_accepting_applications():
            return False
        if job_id and job_id not in self._closed_job_set:
            self._closed_job_set.add(job_id)
            self.closed_job_ids.append(job_id)
        log.warning(
            "职位已不再接受申请（%s），跳过 Easy Apply: job_id=%s",
            phase,
            job_id,
        )
        self._close_tab_if_opened_for_this_job(open_in_new_tab)
        return True

    def _close_tab_if_opened_for_this_job(self, open_in_new_tab: bool) -> None:
        """关掉当前岗位页；若仅剩单标签无法关闭，则跳到空白页避免停留在关岗职位。"""
        try:
            handles = self.driver.window_handles
        except Exception:
            handles = []
        # 多标签时始终关闭当前岗位页（不要求必须由本函数新开），避免卡着关岗页。
        if len(handles) > 1:
            try:
                self.driver.close()
            except Exception:
                pass
            try:
                rest = self.driver.window_handles
                if rest:
                    self.driver.switch_to.window(rest[-1])
            except Exception:
                pass
            return
        # 单标签无法 close：切离岗位详情页，避免看起来“没关闭”。
        try:
            self.driver.get("about:blank")
        except Exception:
            pass

    def _find_easy_apply_apply_href(self) -> Optional[str]:
        """站内 Easy Apply 的 <a href>（含 openSDUIApplyFlow 或 /jobs/view/.../apply/）。"""
        for xp in (
            "//a[contains(@href,'openSDUIApplyFlow')]",
            "//a[contains(@href,'/apply/') and contains(@href,'/jobs/view/')]",
        ):
            try:
                for a in self.driver.find_elements(By.XPATH, xp):
                    try:
                        if not a.is_displayed():
                            continue
                    except Exception:
                        continue
                    raw = (a.get_attribute("href") or "").strip()
                    if not raw:
                        continue
                    if raw.lower().startswith("http"):
                        return raw
                    return urljoin(self.driver.current_url, raw)
            except Exception:
                continue
        return None

    def _wait_for_apply_wizard_ready(
        self, job_id: str, open_in_new_tab: bool
    ) -> tuple[bool, bool]:
        """
        先短等弹层/内联向导；若仍只有 /jobs/view/ 且 DOM 无表单，则对 apply 链接 driver.get（绕过 SPA 点击不生效）。

        返回 (向导已出现, 是否已按关岗处理)。第二项为 True 时调用方应直接结束本岗位，勿记为「向导超时」。
        轮询中优先检测「No longer accepting applications」等关岗提示并走关标签流程。
        """
        if self._handle_closed_job_if_any(job_id, open_in_new_tab, "等待向导出现时"):
            return False, True

        t_click = time.time()
        while time.time() - t_click < 10.0:
            if self._handle_closed_job_if_any(job_id, open_in_new_tab, "等待向导(点击后)"):
                return False, True
            if _apply_wizard_root(self.driver) is not None:
                return True, False
            time.sleep(0.28)

        href = self._find_easy_apply_apply_href()
        if href:
            log.info(
                "Easy Apply 点击后 10s 内未检测到向导，改为直接打开 apply 链接: job_id=%s",
                job_id,
            )
            self.driver.get(href)
            time.sleep(0.8)
            if self._handle_closed_job_if_any(job_id, open_in_new_tab, "打开 apply 链接后"):
                return False, True

        t_nav = time.time()
        while time.time() - t_nav < 26.0:
            if self._handle_closed_job_if_any(job_id, open_in_new_tab, "打开 apply 页后等待向导"):
                return False, True
            if _apply_wizard_root(self.driver) is not None:
                return True, False
            time.sleep(0.35)
        ok = _apply_wizard_root(self.driver) is not None
        return ok, False

    def _click_easy_apply_button(self) -> bool:
        """LinkedIn 常把 Easy Apply 做成 <a href=.../apply/?openSDUIApplyFlow=...>，无 jobs-apply-button 类名。"""
        xpaths = [
            # 新版：链接式 Easy Apply（你提供的 DOM）
            "//a[contains(@href,'openSDUIApplyFlow')]",
            "//a[contains(@href,'/apply/') and contains(@href,'/jobs/view/')]",
            "//a[contains(@aria-label,'Easy Apply') or contains(@aria-label,'easy apply')]",
            "//button[contains(@class,'jobs-apply-button') and contains(.,'Easy')]",
            "//button[contains(@class,'jobs-apply-button') and contains(@aria-label,'Easy')]",
            "//button[contains(@class,'jobs-apply-button')]",
            "//button[contains(@aria-label,'Easy Apply') or contains(@aria-label,'easy apply')]",
            "//a[contains(@class,'jobs-apply-button')]",
            "//span[contains(normalize-space(.),'Easy Apply')]/ancestor::button[1]",
            "//span[contains(normalize-space(.),'Easy Apply')]/ancestor::*[self::a or self::button][1]",
            "//*[contains(@class,'jobs-apply-button--top-card')]//button",
            "//*[contains(@class,'jobs-apply-button--top-card')]//a[contains(@href,'/apply/')]",
        ]

        seen = set()

        def try_click(el) -> bool:
            try:
                eid = id(el)
                if eid in seen:
                    return False
                seen.add(eid)
                if not el.is_displayed():
                    return False
                tag = (el.tag_name or "").lower()
                # 带 href 的 <a> 在部分 WebDriver 上 is_enabled() 不可靠，不以它为准
                if tag != "a":
                    try:
                        if not el.is_enabled():
                            return False
                    except Exception:
                        pass
            except Exception:
                return False
            href = (el.get_attribute("href") or "").lower()
            # 站内 Easy Apply 入口（你提供的链接形态）
            if "opensduiapplyflow" in href:
                _safe_click(self.driver, el)
                return True
            if "linkedin.com" in href and "/jobs/view/" in href and "/apply/" in href:
                if self._label_says_easy_apply(el):
                    _safe_click(self.driver, el)
                    return True
            if not self._label_says_easy_apply(el):
                return False
            _safe_click(self.driver, el)
            return True

        for xp in xpaths:
            try:
                for b in self.driver.find_elements(By.XPATH, xp):
                    if try_click(b):
                        return True
            except Exception:
                continue

        scope_sels = [
            ".jobs-unified-top-card",
            ".jobs-details-top-card",
            ".jobs-details",
            ".jobs-search-job-details__body",
            "main",
        ]
        for sel in scope_sels:
            try:
                scopes = self.driver.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            for scope in scopes:
                try:
                    if not scope.is_displayed():
                        continue
                except Exception:
                    continue
                try:
                    for b in scope.find_elements(
                        By.CSS_SELECTOR,
                        "button, a[href*='/apply/'], a[href*='openSDUIApplyFlow'], a.artdeco-button",
                    ):
                        if try_click(b):
                            return True
                except Exception:
                    continue

        return False

    def _upload_resume_if_present(self, root, resume_abs: str) -> None:
        try:
            for finput in root.find_elements(By.CSS_SELECTOR, "input[type='file']"):
                try:
                    finput.send_keys(resume_abs)
                    log.debug("已上传简历: %s", resume_abs)
                    time.sleep(0.8)
                except Exception:
                    continue
        except Exception:
            pass

    def _fill_text_fields(self, root, answers: dict[str, Any], job_row: dict) -> None:
        mapping = self._answer_mapping(answers, job_row)
        fields = root.find_elements(
            By.CSS_SELECTOR,
            "input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file']), textarea",
        )
        for el in fields:
            try:
                if not el.is_displayed() or not el.is_enabled():
                    continue
            except StaleElementReferenceException:
                continue
            label = self._field_label(el).lower()
            if not label:
                ph = (el.get_attribute("placeholder") or "").lower()
                label = ph
            val = self._match_answer(label, mapping)
            if not val:
                continue
            try:
                cur = el.get_attribute("value") or ""
                if cur.strip() and len(cur.strip()) > 2:
                    continue
            except Exception:
                pass
            try:
                el.clear()
            except Exception:
                pass
            try:
                el.send_keys(str(val)[:500])
            except Exception:
                pass

    def _answer_mapping(self, answers: dict[str, Any], job_row: dict) -> dict[str, str]:
        full = (answers.get("full_name") or "").strip()
        first, last = "", ""
        if full:
            parts = full.split()
            if len(parts) >= 2:
                first, last = parts[0], parts[-1]
            elif parts:
                first = parts[0]
        extras = answers.get("extra_screening_answers")
        extra_blob = ""
        if isinstance(extras, list):
            extra_blob = " ".join(
                f"{x.get('question','')} {x.get('answer','')}"
                for x in extras
                if isinstance(x, dict)
            )
        bc_row = str(job_row.get("base_country") or "").strip().lower()
        phone_val = str(answers.get("phone") or job_row.get("contact_phone") or "")
        addr_val = str(answers.get("full_address_line") or job_row.get("contact_address") or "")
        country_val = (str(answers.get("country") or "").strip() or str(job_row.get("base_country") or "").strip())
        if bc_row == "switzerland":
            phone_val = str(job_row.get("contact_phone") or "").strip() or _SWISS_DEFAULT_PHONE
            addr_val = str(job_row.get("contact_address") or "").strip() or _SWISS_DEFAULT_ADDRESS
            country_val = "Switzerland"
        return {
            "email": str(answers.get("email") or ""),
            "phone": phone_val,
            "mobile": phone_val,
            "first": first,
            "last": last,
            "name": full,
            "city": str(answers.get("city") or ""),
            "country": country_val,
            "postal": str(answers.get("postal_code") or ""),
            "address": addr_val,
            "linkedin": str(answers.get("linkedin_url") or ""),
            "notice": str(answers.get("notice_period") or ""),
            "authorization": str(answers.get("work_authorization") or ""),
            "experience": str(answers.get("years_of_professional_experience") or ""),
            "extra": extra_blob,
        }

    def _match_answer(self, label: str, m: dict[str, str]) -> str:
        if not label:
            return ""
        # 须先于泛泛的 "phone"，避免「Phone country code」误用手机号填区号下拉
        pairs = [
            ("phone country", "country"),
            ("country code", "country"),
            ("mail", "email"),
            ("email", "email"),
            ("phone", "phone"),
            ("mobile", "phone"),
            ("tel", "phone"),
            ("first name", "first"),
            ("given", "first"),
            ("last name", "last"),
            ("surname", "last"),
            ("family", "last"),
            ("full name", "name"),
            ("name", "name"),
            ("city", "city"),
            ("location", "city"),
            ("country", "country"),
            ("postal", "postal"),
            ("zip", "postal"),
            ("address", "address"),
            ("street", "address"),
            ("linkedin", "linkedin"),
            ("notice", "notice"),
            ("availability", "notice"),
            ("authorized", "authorization"),
            ("legally", "authorization"),
            ("work authorization", "authorization"),
            ("sponsorship", "authorization"),
            ("experience", "experience"),
            ("years", "experience"),
        ]
        for needle, key in pairs:
            if needle in label:
                return m.get(key, "")
        if m.get("extra") and any(
            k in label for k in ("additional", "message", "cover", "why", "motivation", "comments", "question")
        ):
            return m["extra"][:500]
        return ""

    def _select_option_contains_fragment(self, sel: Select, fragment: str) -> bool:
        """按可见文案子串选 option（如 Germany (+49) 匹配 answers.country=Germany）。"""
        frag = (fragment or "").strip()
        if not frag:
            return False
        low = frag.lower()
        try:
            for opt in sel.options:
                txt = (opt.text or "").strip()
                if not txt or "select an option" in txt.lower():
                    continue
                tl = txt.lower()
                if low in tl or tl in low or low.split()[0] in tl:
                    sel.select_by_visible_text(txt)
                    return True
            if len(frag) >= 3:
                sel.select_by_partial_text(frag[: min(24, len(frag))])
                return True
        except Exception:
            return False
        return False

    def _field_label(self, el) -> str:
        eid = el.get_attribute("id") or ""
        if eid:
            try:
                lab = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{eid}']")
                return (lab.text or "").strip()
            except NoSuchElementException:
                pass
        aria = el.get_attribute("aria-label") or ""
        if aria:
            return aria.strip()
        try:
            parent = el.find_element(By.XPATH, "./ancestor::div[contains(@class,'fb-dash-form-element')][1]")
            labs = parent.find_elements(By.CSS_SELECTOR, "label")
            if labs:
                return (labs[0].text or "").strip()
        except Exception:
            pass
        return ""

    def _fill_selects(self, root, answers: dict[str, Any], job_row: dict) -> None:
        """Contact info 步：Email 下拉、Phone country code（+49 格式）、其它国家类 select。"""
        mapping = self._answer_mapping(answers, job_row)
        email = (mapping.get("email") or "").strip()
        country = (mapping.get("country") or "").strip()
        for sel_el in root.find_elements(By.TAG_NAME, "select"):
            try:
                if not sel_el.is_displayed():
                    continue
                lab = self._field_label(sel_el).lower()
            except Exception:
                continue
            try:
                s = Select(sel_el)
                try:
                    cur = (s.first_selected_option.text or "").strip().lower()
                    if cur and "select an option" not in cur:
                        continue
                except Exception:
                    pass

                is_phone_cc = (
                    "phone country" in lab
                    or "country code" in lab
                    or ("phone" in lab and "country" in lab)
                )
                if "email" in lab and email:
                    self._select_option_contains_fragment(s, email)
                    continue
                if is_phone_cc and country:
                    self._select_option_contains_fragment(s, country)
                    continue
                if ("country" in lab or "land" in lab) and country and not is_phone_cc and "email" not in lab:
                    self._select_option_contains_fragment(s, country)
            except Exception:
                continue

    def _answer_yes_no_radios(self, root) -> None:
        """对「是否授权工作」类单选，优先选 Yes / Ja。"""
        for block in root.find_elements(
            By.XPATH,
            ".//fieldset[contains(.,'authorized') or contains(.,'legally') or contains(.,'permit') or contains(.,'Arbeit')]",
        ):
            try:
                for inp in block.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
                    v = (inp.get_attribute("value") or "").lower()
                    if v in ("yes", "ja", "true", "1"):
                        if inp.is_displayed():
                            _safe_click(self.driver, inp)
                            break
            except Exception:
                continue

    def _click_next(self) -> bool:
        """Next / Review 等主按钮；Additional Questions 步为 Review 而非 Next。"""
        root = _apply_wizard_root(self.driver)

        def try_ctx(finder, rel: bool) -> bool:
            prefix = ".//" if rel else "//"
            xps = [
                prefix + "button[@data-easy-apply-next-button]",
                prefix + "button[@data-live-test-easy-apply-next-button]",
                prefix + "button[@data-live-test-easy-apply-review-button]",
                prefix + "button[contains(@aria-label,'Review your application')]",
                prefix + "button[contains(@aria-label,'Review')]",
                prefix + "button[@aria-label='Continue to next step']",
                prefix + "button[contains(@aria-label,'Continue to next')]",
                prefix + "button[contains(@aria-label,'Weiter')]",
                prefix
                + "button[contains(@class,'artdeco-button--primary')]"
                + "[.//span[normalize-space(.)='Next']]",
                prefix
                + "button[contains(@class,'artdeco-button--primary')]"
                + "[.//span[normalize-space(.)='Weiter']]",
                prefix
                + "button[contains(@class,'artdeco-button--primary')]"
                + "[.//span[normalize-space(.)='Review']]",
            ]
            for xp in xps:
                try:
                    for b in finder.find_elements(By.XPATH, xp):
                        try:
                            if not b.is_displayed():
                                continue
                            try:
                                if not b.is_enabled():
                                    continue
                            except Exception:
                                pass
                        except Exception:
                            continue
                        t = (b.text or "").lower()
                        if "submit" in t or "einreichen" in t or "bewerben" in t:
                            continue
                        _safe_click(self.driver, b)
                        return True
                except Exception:
                    continue
            for sel in (
                "button[data-easy-apply-next-button]",
                "button[data-live-test-easy-apply-next-button]",
                "button[data-live-test-easy-apply-review-button]",
            ):
                try:
                    for b in finder.find_elements(By.CSS_SELECTOR, sel):
                        try:
                            if not b.is_displayed():
                                continue
                        except Exception:
                            continue
                        _safe_click(self.driver, b)
                        return True
                except Exception:
                    continue
            return False

        if root is not None and try_ctx(root, rel=True):
            return True
        return try_ctx(self.driver, rel=False)

    def _submit_xpaths(self) -> list[str]:
        return [
            "//button[contains(@class,'artdeco-button--primary') and .//span[contains(.,'Submit application')]]",
            "//button[contains(@class,'artdeco-button--primary') and .//span[contains(.,'Einreichen')]]",
            "//button[contains(@aria-label,'Submit')]",
        ]

    def _submit_button_visible(self) -> bool:
        for xp in self._submit_xpaths():
            try:
                for b in self.driver.find_elements(By.XPATH, xp):
                    if b.is_displayed() and b.is_enabled():
                        return True
            except Exception:
                continue
        return False

    def _click_submit(self) -> bool:
        for xp in self._submit_xpaths():
            try:
                for b in self.driver.find_elements(By.XPATH, xp):
                    if b.is_displayed() and b.is_enabled():
                        _safe_click(self.driver, b)
                        return True
            except Exception:
                continue
        return False

    def _wait_post_submit(self) -> bool:
        deadline = time.time() + 25
        while time.time() < deadline:
            if self._looks_submitted():
                return True
            if _apply_wizard_root(self.driver) is None:
                time.sleep(0.6)
                return self._looks_submitted()
            time.sleep(0.5)
        return self._looks_submitted()

    def _looks_submitted(self) -> bool:
        src = (self.driver.page_source or "").lower()
        if "submitted" in src and "application" in src:
            return True
        if "bewerbung gesendet" in src or "application was sent" in src:
            return True
        try:
            el = self.driver.find_element(
                By.XPATH,
                "//*[contains(@class,'jobs-s-apply') and (contains(.,'Applied') or contains(.,'Beworben'))]",
            )
            return el.is_displayed()
        except NoSuchElementException:
            return False


def run_prepared_jobs(
    driver: WebDriver,
    prepared_rows: list[dict[str, Any]],
    artifacts_base: Path,
    pause_between_jobs_s: float = 4.0,
    *,
    submit_application: bool = True,
    new_tab_per_job: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """
    对 auto_applied 风格的记录依次执行 Easy Apply。

    submit_application=False：填完向导至「提交申请」前即停，不点提交。
    new_tab_per_job=True：除第一个岗位外，每个岗位在新浏览器标签打开，便于保留多页手动提交。

    返回 (成功完成 job_id 列表, 已检测为 closed 的 job_id 列表, 未找到 Easy Apply 按已投递处理的 job_id 列表)。
    填表-only 成功也算成功，但不会代表已在 LinkedIn 提交。
    """
    auto = EasyApplyAutomation(driver)
    ok: list[str] = []
    n = len(prepared_rows)
    for i, row in enumerate(prepared_rows):
        jid = str(row.get("job_id") or "")
        if not jid:
            continue
        open_in_new = bool(new_tab_per_job and i > 0)
        try:
            if auto.apply_one(
                row,
                artifacts_base,
                submit_application=submit_application,
                open_in_new_tab=open_in_new,
            ):
                ok.append(jid)
        except Exception as e:
            log.exception("Easy Apply 异常 job_id=%s: %s", jid, e)
        if i < n - 1 and pause_between_jobs_s > 0:
            time.sleep(pause_between_jobs_s)
    return ok, auto.closed_job_ids, auto.no_easy_apply_job_ids
