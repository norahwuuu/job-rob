"""
LinkedIn Easy Apply 浏览器自动化：打开职位页、点击 Easy Apply、在向导中填写并提交。

依赖与 linkedin_scraper 相同的 Selenium 环境；选择器随 LinkedIn 改版可能需调整。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
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


def _modal_root(driver: WebDriver):
    selectors = [
        "div.jobs-easy-apply-modal__content",
        "div[data-test-modal-container]",
        "div.artdeco-modal.jobs-easy-apply-modal",
        "div[role='dialog']",
    ]
    for sel in selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in els:
                if e.is_displayed():
                    return e
        except Exception:
            continue
    return None


class EasyApplyAutomation:
    def __init__(self, driver: WebDriver, default_wait_s: int = 22) -> None:
        self.driver = driver
        self.default_wait_s = default_wait_s

    def _wait(self, seconds: Optional[float] = None) -> WebDriverWait:
        return WebDriverWait(self.driver, int(seconds or self.default_wait_s))

    def apply_one(self, job_row: dict[str, Any], artifacts_base: Path) -> bool:
        """打开 job_row['url']，完成一次 Easy Apply。成功返回 True。"""
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
        self.driver.get(url)
        time.sleep(2.5)

        if not self._click_easy_apply_button():
            log.error("未找到可点击的 Easy Apply 按钮: job_id=%s", job_id)
            return False

        time.sleep(1.5)
        try:
            self._wait(25).until(lambda d: _modal_root(d) is not None)
        except TimeoutException:
            log.error("Easy Apply 弹窗未出现: job_id=%s", job_id)
            return False

        for step in range(22):
            root = _modal_root(self.driver)
            if root is None:
                if self._looks_submitted():
                    log.info("弹窗已关闭且页面显示已投递迹象: job_id=%s", job_id)
                    return True
                time.sleep(0.6)
                continue

            try:
                self._upload_resume_if_present(root, str(resume_path))
                self._fill_text_fields(root, answers, job_row)
                self._fill_selects(root, answers)
                self._answer_yes_no_radios(root)
            except StaleElementReferenceException:
                time.sleep(0.5)
                continue

            if self._submit_button_visible():
                time.sleep(2.0)
            if self._click_submit():
                if self._wait_post_submit():
                    log.info("已提交申请: job_id=%s", job_id)
                    return True
                log.warning("点击提交后未确认成功，可能需人工检查: job_id=%s", job_id)
                return False

            if not self._click_next():
                log.warning("未找到下一步/提交按钮，可能卡在某步: job_id=%s step=%s", job_id, step)
                return False
            time.sleep(1.2)

        log.error("超过最大步数仍未完成: job_id=%s", job_id)
        return False

    def _click_easy_apply_button(self) -> bool:
        xpaths = [
            "//button[contains(@class,'jobs-apply-button') and contains(.,'Easy')]",
            "//button[contains(@class,'jobs-apply-button') and contains(@aria-label,'Easy Apply')]",
            "//button[contains(@class,'jobs-apply-button')]",
        ]
        for xp in xpaths:
            try:
                buttons = self.driver.find_elements(By.XPATH, xp)
                for b in buttons:
                    if not b.is_displayed():
                        continue
                    t = (b.text or "").lower()
                    a = (b.get_attribute("aria-label") or "").lower()
                    if "easy apply" in t or "easy apply" in a or "easy" in t:
                        _safe_click(self.driver, b)
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
        return {
            "email": str(answers.get("email") or ""),
            "phone": str(answers.get("phone") or job_row.get("contact_phone") or ""),
            "mobile": str(answers.get("phone") or ""),
            "first": first,
            "last": last,
            "name": full,
            "city": str(answers.get("city") or ""),
            "country": str(answers.get("country") or ""),
            "postal": str(answers.get("postal_code") or ""),
            "address": str(answers.get("full_address_line") or job_row.get("contact_address") or ""),
            "linkedin": str(answers.get("linkedin_url") or ""),
            "notice": str(answers.get("notice_period") or ""),
            "authorization": str(answers.get("work_authorization") or ""),
            "experience": str(answers.get("years_of_professional_experience") or ""),
            "extra": extra_blob,
        }

    def _match_answer(self, label: str, m: dict[str, str]) -> str:
        if not label:
            return ""
        pairs = [
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

    def _fill_selects(self, root, answers: dict[str, Any]) -> None:
        country = (answers.get("country") or "").strip()
        if not country:
            return
        for sel_el in root.find_elements(By.TAG_NAME, "select"):
            try:
                if not sel_el.is_displayed():
                    continue
                lab = self._field_label(sel_el).lower()
                if "country" not in lab and "land" not in lab:
                    continue
                Select(sel_el).select_by_visible_text(country)
            except Exception:
                try:
                    Select(sel_el).select_by_partial_text(country[:6])
                except Exception:
                    pass

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
        xps = [
            "//button[contains(@class,'artdeco-button--primary') and .//span[text()='Next']]",
            "//button[contains(@class,'artdeco-button--primary') and .//span[text()='Weiter']]",
            "//button[@aria-label='Continue to next step']",
            "//button[contains(@aria-label,'Continue to next')]",
            "//button[contains(@aria-label,'Weiter')]",
        ]
        for xp in xps:
            try:
                for b in self.driver.find_elements(By.XPATH, xp):
                    if b.is_displayed() and b.is_enabled():
                        t = (b.text or "").lower()
                        if "submit" in t or "einreichen" in t or "bewerben" in t:
                            continue
                        _safe_click(self.driver, b)
                        return True
            except Exception:
                continue
        return False

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
            if _modal_root(self.driver) is None:
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
) -> list[str]:
    """
    对 auto_applied 风格的记录依次执行 Easy Apply。
    返回成功投递的 job_id 列表。
    """
    auto = EasyApplyAutomation(driver)
    ok: list[str] = []
    for row in prepared_rows:
        jid = str(row.get("job_id") or "")
        if not jid:
            continue
        try:
            if auto.apply_one(row, artifacts_base):
                ok.append(jid)
        except Exception as e:
            log.exception("Easy Apply 异常 job_id=%s: %s", jid, e)
        time.sleep(pause_between_jobs_s)
    return ok
