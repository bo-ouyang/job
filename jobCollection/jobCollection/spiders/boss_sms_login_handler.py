import asyncio
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pyautogui  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    pyautogui = None

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    gw = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    cv2 = None

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    Image = None


class BossSmsLoginHandler:
    """Handle SMS login and puzzle slider verification for BOSS."""

    LOGIN_URL = "https://www.zhipin.com/web/user/login"

    PHONE_SELECTORS = [
        "input[name='phone']",
        "input.ipt-phone",
        "input[placeholder='手机号']",
    ]
    SMS_TAB_SELECTORS = [
        ".sign-tab .link-sms",
        ".sign-form .link-sms",
        ".link-sms",
    ]
    SEND_SMS_SELECTORS = [
        "button.btn-sms",
        ".btn-sms",
        "div.btn-sms",
        "[ka='send_sms_code_click']",
        ".sms-input-wrapper .btn-sms",
        ".row-code button[data-url*='smsCode']",
        "button[data-url*='smsCode']",
    ]
    SEND_SMS_TEXTS = [
        "发送验证码",
    ]
    CLICK_VERIFY_SELECTORS = [
        ".geetest_btn",
        ".geetest_radar_tip",
        "[ka*='verify']",
        "[class*='verify'] .btn",
        "[class*='captcha'] .btn",
    ]
    CLICK_VERIFY_TEXTS = [
        "点击验证",
        "请点击验证",
        "点击按钮进行验证",
        "请先点击验证",
    ]
    SMS_CODE_SELECTORS = [
        "input[name='phoneCode']",
        "input.ipt-sms",
        "input[placeholder='短信验证码']",
    ]
    SUBMIT_SELECTORS = [
        ".sign-form .form-btn .btn",
        "form button[type='submit']",
        ".sign-form button.btn",
    ]
    LOGIN_READY_SELECTORS = [
        ".nav-figure",
        ".header-username",
        ".nav-user-enter",
    ]
    CAPTCHA_CONTAINER_SELECTORS = [
        ".yidun_popup",
        ".yidun_modal",
        ".geetest_panel",
        ".geetest_box",
        "[class*='captcha']",
        "[class*='verify']",
    ]
    SLIDER_HANDLE_SELECTORS = [
        ".yidun_slider",
        ".yidun_slider__icon",
        ".geetest_btn",
        ".geetest_slider_button",
        "[class*='slider']",
    ]
    TRACK_SELECTORS = [
        ".yidun_slider__track",
        ".geetest_track",
        "[class*='slider-track']",
        "[class*='verify-bar']",
    ]
    REFRESH_SELECTORS = [
        ".yidun_refresh",
        ".geetest_refresh",
        "[class*='refresh']",
    ]

    def __init__(
        self,
        page: Any,
        logger: Any,
        account: Dict[str, Any],
        account_index: int,
        work_dir: str,
        is_logged_in_cb,
    ) -> None:
        self.page = page
        self.logger = logger
        self.account = account
        self.account_index = account_index
        self.work_dir = Path(work_dir)
        self.is_logged_in_cb = is_logged_in_cb
        self.artifact_dir = self.work_dir / f"login_debug_account_{account_index + 1}"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.slider_max_retries = int(self.account.get("slider_max_retries") or os.getenv("BOSS_SLIDER_MAX_RETRIES", "3"))
        self.slider_calibration = int(self.account.get("slider_calibration") or os.getenv("BOSS_SLIDER_CALIBRATION", "14"))
        self.sms_poll_interval = float(self.account.get("sms_poll_interval") or os.getenv("BOSS_SMS_CODE_POLL_INTERVAL", "2"))
        self.use_real_mouse = str(self.account.get("use_real_mouse") or os.getenv("BOSS_USE_REAL_MOUSE", "1")).strip().lower() not in {"0", "false", "no"}

    def _run_js(self, script: str, *args: Any) -> Any:
        if not args:
            return self.page.run_js(script)
        payload = json.dumps(args, ensure_ascii=False)
        wrapped = f"return (function(){{{script}}}).apply(null, {payload});"
        return self.page.run_js(wrapped)

    def _selector_label(self, selector: Optional[str]) -> str:
        return selector or "<none>"

    def _rect_label(self, rect: Optional[Dict[str, float]]) -> str:
        if not rect:
            return "<no-rect>"
        return (
            f"x={rect['x']:.1f},y={rect['y']:.1f},"
            f"w={rect['width']:.1f},h={rect['height']:.1f}"
        )

    def can_auto_login(self) -> bool:
        mobile = str(self.account.get("mobile") or "").strip()
        login_mode = str(self.account.get("login_mode") or "").strip().lower()
        if not mobile:
            return False
        return login_mode in {"auto", "auto_sms", "sms"} or not login_mode

    async def login(self, timeout: float) -> bool:
        if not self.page:
            return False

        mobile = str(self.account.get("mobile") or "").strip()
        if not mobile:
            self.logger.info("Skip auto login because mobile is empty.")
            return False

        sms_timeout = float(self.account.get("sms_code_timeout") or timeout)
        self.logger.info(f"Try SMS login for account [{self.account.get('name') or self.account_index + 1}].")

        try:
            self.page.set.load_mode.normal()
        except Exception:
            pass

        try:
            self.page.get(self.LOGIN_URL)
            await asyncio.sleep(1.2)
            await self._switch_to_sms_login()
            await self._fill_mobile(mobile)
            if not await self._click_send_sms():
                return False

            await self._trigger_click_verification_if_needed()

            slider_ok = await self._solve_slider_if_needed()
            if not slider_ok:
                self.logger.info("Slider verification failed, will fallback to manual login.")
                return False

            code = await self._wait_for_sms_code(sms_timeout)
            if not code:
                self.logger.info("No SMS code received within timeout.")
                return False

            await self._fill_sms_code(code)
            await self._submit_login()

            deadline = time.time() + max(10.0, min(timeout, 30.0))
            while time.time() < deadline:
                await asyncio.sleep(1.0)
                if self.is_logged_in_cb():
                    self.logger.info("SMS login completed.")
                    return True

            self.logger.info("SMS form submitted but login state was not confirmed.")
            return False
        except Exception as exc:
            self.logger.info(f"Auto SMS login raised exception: {exc}")
            return False

    async def _switch_to_sms_login(self) -> None:
        self.logger.info("Try switching to SMS login tab.")
        for _ in range(2):
            if await self._click_first_visible(self.SMS_TAB_SELECTORS):
                self.logger.info("Switched to SMS login tab.")
                await asyncio.sleep(0.5)
                return
        self.logger.info("Failed to switch to SMS login tab.")

    async def _fill_mobile(self, mobile: str) -> None:
        country_code = str(self.account.get("country_code") or "+86").strip()
        self.logger.info(f"Fill mobile start, country_code={country_code}, mobile_len={len(mobile)}")
        await self._set_input_value(["input[name='areaCode']"], country_code)
        await self._type_input_value(self.PHONE_SELECTORS, mobile, delay_min=0.12, delay_max=0.28)
        await asyncio.sleep(0.3)
        self.logger.info("Fill mobile finished.")

    async def _click_send_sms(self) -> bool:
        self.logger.info("Try clicking send SMS button.")
        clicked = await self._click_first_visible(self.SEND_SMS_SELECTORS)
        if not clicked:
            clicked = await self._click_button_by_text(self.SEND_SMS_TEXTS)
        if clicked:
            self.logger.info("Clicked send SMS button.")
            await asyncio.sleep(0.8)
        else:
            self.logger.info("Send SMS button click failed.")
        return clicked

    async def _fill_sms_code(self, code: str) -> None:
        self.logger.info(f"Fill SMS code start, code_len={len(code)}")
        await self._type_input_value(self.SMS_CODE_SELECTORS, code, delay_min=0.08, delay_max=0.18)
        await asyncio.sleep(0.2)
        self.logger.info("Fill SMS code finished.")

    async def _submit_login(self) -> None:
        self.logger.info("Try clicking login submit button.")
        await self._click_first_visible(self.SUBMIT_SELECTORS)

    async def _trigger_click_verification_if_needed(self) -> bool:
        self.logger.info("Check whether click verification is required before slider.")
        clicked = await self._click_first_visible(self.CLICK_VERIFY_SELECTORS)
        if not clicked:
            clicked = await self._click_button_by_text(self.CLICK_VERIFY_TEXTS)
        if clicked:
            self.logger.info("Click verification trigger executed.")
            await asyncio.sleep(1.0)
            return True
        self.logger.info("No explicit click verification trigger found.")
        return False

    async def _solve_slider_if_needed(self) -> bool:
        await asyncio.sleep(1.0)
        if not await self._has_slider():
            return True

        for attempt in range(1, self.slider_max_retries + 1):
            self.logger.info(f"Try slider verification, attempt {attempt}/{self.slider_max_retries}.")
            if await self._solve_slider_once():
                await asyncio.sleep(1.2)
                if not await self._has_slider():
                    return True
            await self._refresh_slider()
            await asyncio.sleep(1.0)
        return False

    async def _solve_slider_once(self) -> bool:
        handle_selector = await self._pick_visible_selector(self.SLIDER_HANDLE_SELECTORS)
        track_selector = await self._pick_visible_selector(self.TRACK_SELECTORS)
        container_selector = await self._pick_visible_selector(self.CAPTCHA_CONTAINER_SELECTORS)
        if not handle_selector:
            self.logger.info("Slider handle selector not found.")
            return False

        if not track_selector:
            self.logger.info(
                f"Slider track not found yet, trying pre-slider click on selector={handle_selector}."
            )
            clicked = await self._click_specific_selector(handle_selector)
            self.logger.info(f"Pre-slider click result selector={handle_selector}, clicked={clicked}")
            await asyncio.sleep(1.0)
            track_selector = await self._pick_visible_selector(self.TRACK_SELECTORS)
            container_selector = await self._pick_visible_selector(self.CAPTCHA_CONTAINER_SELECTORS)

        await self._hover_selector(handle_selector)
        await asyncio.sleep(0.8)

        container_rect = await self._get_rect(container_selector) if container_selector else None
        handle_rect = await self._get_rect(handle_selector)
        track_rect = await self._get_rect(track_selector) if track_selector else None
        if not handle_rect:
            self.logger.info("Slider handle rect not found.")
            return False

        screenshot_path = self.artifact_dir / f"slider_{int(time.time() * 1000)}.png"
        image_path = await self._capture_region(container_rect or track_rect, screenshot_path)
        if not image_path:
            self.logger.info("Slider screenshot capture failed.")
            return False

        offset = self._estimate_gap_offset(image_path)
        if offset is None:
            self.logger.info("Slider gap offset was not detected.")
            return False

        if track_rect and container_rect:
            scale = track_rect["width"] / max(container_rect["width"], 1.0)
            drag_distance = offset * scale
        else:
            drag_distance = offset
        drag_distance = max(20.0, drag_distance - self.slider_calibration)

        self.logger.info(f"Slider drag distance estimated at {drag_distance:.1f}px.")
        return await self._drag_slider(handle_rect, drag_distance)

    async def _refresh_slider(self) -> None:
        await self._click_first_visible(self.REFRESH_SELECTORS)

    async def _has_slider(self) -> bool:
        handle = await self._pick_visible_selector(self.SLIDER_HANDLE_SELECTORS)
        if handle:
            return True
        container = await self._pick_visible_selector(self.CAPTCHA_CONTAINER_SELECTORS)
        return container is not None

    async def _wait_for_sms_code(self, timeout: float) -> Optional[str]:
        preset_code = str(self.account.get("sms_code") or "").strip()
        if re.fullmatch(r"\d{4,8}", preset_code):
            return preset_code

        source = str(self.account.get("sms_code_source") or "file").strip().lower()
        code_file = self._sms_code_file()
        self.logger.info(f"Waiting for SMS code from {source}: {code_file}")

        deadline = time.time() + timeout
        while time.time() < deadline:
            code = None
            if source in {"file", "manual", ""}:
                code = self._read_sms_code_file(code_file)
            if code:
                self.logger.info("SMS code detected from configured source.")
                return code
            await asyncio.sleep(self.sms_poll_interval)
        return None

    def _sms_code_file(self) -> Path:
        configured = str(self.account.get("sms_code_file") or "").strip()
        if configured:
            return Path(configured)
        return self.work_dir / f"boss_sms_code_account_{self.account_index + 1}.txt"

    def _read_sms_code_file(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            return None
        match = re.search(r"\b(\d{4,8})\b", text)
        return match.group(1) if match else None

    async def _pick_visible_selector(self, selectors: List[str]) -> Optional[str]:
        self.logger.info(f"Pick visible selector from {selectors}")
        script = """
        const selectors = arguments[0];
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' &&
                   style.visibility !== 'hidden' &&
                   parseFloat(style.opacity || '1') > 0 &&
                   rect.width > 0 &&
                   rect.height > 0;
        };
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (isVisible(el)) return sel;
        }
        return null;
        """
        try:
            picked = self._run_js(script, selectors)
            self.logger.info(f"Visible selector picked: {self._selector_label(picked)}")
            return picked or None
        except Exception as exc:
            self.logger.info(f"Pick visible selector failed: {exc}")
            return None

    async def _click_first_visible(self, selectors: List[str]) -> bool:
        selector = await self._pick_visible_selector(selectors)
        if not selector:
            self.logger.info(f"Click failed because no visible selector matched: {selectors}")
            return False
        return await self._click_specific_selector(selector)

    async def _click_specific_selector(self, selector: str) -> bool:
        self.logger.info(f"Click target selector resolved: {self._selector_label(selector)}")
        moved = await self._move_mouse_to_selector(selector)
        self.logger.info(f"Mouse move before click selector={selector}, moved={moved}")
        element = None
        try:
            element = self.page.ele(f"css:{selector}", timeout=1)
        except Exception:
            element = None
        if element is not None:
            try:
                if hasattr(element, "click"):
                    element.click()
                    self.logger.info(f"Element click succeeded for selector={selector}")
                    return True
            except Exception as exc:
                self.logger.info(f"Element click failed for selector={selector}: {exc}")
        script = """
        const sel = arguments[0];
        const el = document.querySelector(sel);
        if (!el) return false;
        el.click();
        return true;
        """
        try:
            clicked = bool(self._run_js(script, selector))
            self.logger.info(f"JS click result selector={selector}, clicked={clicked}")
            return clicked
        except Exception as exc:
            self.logger.info(f"JS click failed for selector={selector}: {exc}")
            return False

    async def _click_button_by_text(self, texts: List[str]) -> bool:
        self.logger.info(f"Try clicking button by texts: {texts}")
        selector = await self._pick_button_selector_by_text(texts)
        if not selector:
            self.logger.info(f"Click by text failed because no button matched texts: {texts}")
            return False
        self.logger.info(f"Button by text resolved selector: {selector}")
        moved = await self._move_mouse_to_selector(selector)
        self.logger.info(f"Mouse move before text button click selector={selector}, moved={moved}")

        element = None
        try:
            element = self.page.ele(f"css:{selector}", timeout=1)
        except Exception:
            element = None
        if element is not None:
            try:
                if hasattr(element, "click"):
                    element.click()
                    self.logger.info(f"Element click by text succeeded for selector={selector}")
                    return True
            except Exception as exc:
                self.logger.info(f"Element click by text failed for selector={selector}: {exc}")

        try:
            clicked = bool(self._run_js(
                """
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return false;
                el.click();
                return true;
                """,
                selector,
            ))
            self.logger.info(f"JS click by text result selector={selector}, clicked={clicked}")
            return clicked
        except Exception as exc:
            self.logger.info(f"JS click by text failed for selector={selector}: {exc}")
            return False

    async def _pick_button_selector_by_text(self, texts: List[str]) -> Optional[str]:
        self.logger.info(f"Pick button selector by texts: {texts}")
        script = """
        const texts = arguments[0] || [];
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' &&
                   style.visibility !== 'hidden' &&
                   parseFloat(style.opacity || '1') > 0 &&
                   rect.width > 0 &&
                   rect.height > 0;
        };
        const cssEscape = (value) => {
            if (window.CSS && typeof window.CSS.escape === 'function') {
                return window.CSS.escape(value);
            }
            return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
        };
        const nodes = Array.from(document.querySelectorAll(
            "button, .btn, .btn-sms, [ka='send_sms_code_click'], input[type='button'], input[type='submit'], div, a, span"
        ));
        const findClickableTarget = (el) => {
            if (!el) return null;
            const candidates = [el, el.parentElement, el.parentElement?.parentElement];
            for (const item of candidates) {
                if (!item) continue;
                if (!isVisible(item)) continue;
                const text = (item.innerText || item.textContent || item.value || '').trim();
                if (
                    item.tagName === 'BUTTON' ||
                    item.classList.contains('btn') ||
                    item.classList.contains('btn-sms') ||
                    item.getAttribute('ka') === 'send_sms_code_click' ||
                    text.includes('发送验证码')
                ) {
                    return item;
                }
            }
            return null;
        };
        for (const targetText of texts) {
            const matchedSource = nodes.find((el) => {
                const text = (el.innerText || el.textContent || el.value || '').trim();
                return text === targetText || text.includes(targetText);
            });
            const matched = findClickableTarget(matchedSource);
            if (matched) {
                if (!matched.id) {
                    matched.id = `boss-auto-btn-${Math.random().toString(36).slice(2, 10)}`;
                }
                return `#${cssEscape(matched.id)}`;
            }
        }
        return null;
        """
        try:
            selector = self._run_js(script, texts)
            self.logger.info(f"Button selector by text picked: {self._selector_label(selector)}")
            return selector or None
        except Exception as exc:
            self.logger.info(f"Pick button selector by text failed: {exc}")
            return None

    async def _set_input_value(self, selectors: List[str], value: str) -> bool:
        selector = await self._pick_visible_selector(selectors)
        if not selector:
            self.logger.info(f"Set input value failed because no selector matched: {selectors}")
            return False
        self.logger.info(
            f"Set input value selector={selector}, value_len={len(value)}, "
            f"is_real_mouse={self.use_real_mouse}"
        )
        moved = await self._move_mouse_to_selector(selector)
        self.logger.info(f"Mouse move before set input selector={selector}, moved={moved}")
        script = """
        const sel = arguments[0];
        const value = arguments[1];
        const el = document.querySelector(sel);
        if (!el) return false;
        el.focus();
        el.value = '';
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
        """
        try:
            ok = bool(self._run_js(script, selector, value))
            self.logger.info(f"Set input value result selector={selector}, ok={ok}")
            return ok
        except Exception as exc:
            self.logger.info(f"Set input value failed for selector={selector}: {exc}")
            return False

    async def _type_input_value(
        self,
        selectors: List[str],
        value: str,
        delay_min: float = 0.08,
        delay_max: float = 0.2,
    ) -> bool:
        selector = await self._pick_visible_selector(selectors)
        if not selector:
            self.logger.info(f"Type input failed because no selector matched: {selectors}")
            return False
        self.logger.info(
            f"Type input start selector={selector}, value_len={len(value)}, "
            f"delay_range=({delay_min:.2f},{delay_max:.2f})"
        )

        element = None
        try:
            element = self.page.ele(f"css:{selector}", timeout=1)
        except Exception as exc:
            self.logger.info(f"Resolve element for typing failed selector={selector}: {exc}")
            element = None

        if element is not None:
            try:
                await self._move_mouse_to_selector(selector)
                if hasattr(element, "click"):
                    element.click()
                    await asyncio.sleep(random.uniform(0.12, 0.24))
                if hasattr(element, "clear"):
                    element.clear()
                else:
                    await self._clear_input_by_js(selector)

                typed = False
                for ch in value:
                    if hasattr(element, "input"):
                        element.input(ch)
                        typed = True
                    elif hasattr(element, "type"):
                        element.type(ch)
                        typed = True
                    else:
                        break
                    await asyncio.sleep(random.uniform(delay_min, delay_max))

                if typed:
                    await self._dispatch_change(selector)
                    self.logger.info(f"Type input finished via element API selector={selector}")
                    return True
            except Exception as exc:
                self.logger.info(f"Element typing failed selector={selector}: {exc}")

        self.logger.info(f"Type input fallback to JS selector={selector}")
        return await self._type_input_value_by_js(selector, value, delay_min=delay_min, delay_max=delay_max)

    async def _type_input_value_by_js(
        self,
        selector: str,
        value: str,
        delay_min: float,
        delay_max: float,
    ) -> bool:
        try:
            await self._move_mouse_to_selector(selector)
            self.logger.info(f"JS typing focus start selector={selector}")
            focused = bool(self._run_js(
                """
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return false;
                el.click();
                el.focus();
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
                return true;
                """,
                selector,
            ))
            if not focused:
                self.logger.info(f"JS typing focus failed selector={selector}")
                return False

            for ch in value:
                ok = bool(self._run_js(
                    """
                    const sel = arguments[0];
                    const ch = arguments[1];
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    const code = ch.charCodeAt(0);
                    el.dispatchEvent(new KeyboardEvent('keydown', { key: ch, bubbles: true, keyCode: code, which: code }));
                    el.dispatchEvent(new KeyboardEvent('keypress', { key: ch, bubbles: true, keyCode: code, which: code }));
                    el.value = `${el.value}${ch}`;
                    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: ch, inputType: 'insertText' }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { key: ch, bubbles: true, keyCode: code, which: code }));
                    return true;
                    """,
                    selector,
                    ch,
                ))
                if not ok:
                    self.logger.info(f"JS typing failed mid-way selector={selector}, ch={ch}")
                    return False
                await asyncio.sleep(random.uniform(delay_min, delay_max))
            await self._dispatch_change(selector)
            self.logger.info(f"JS typing finished selector={selector}")
            return True
        except Exception as exc:
            self.logger.info(f"JS typing exception selector={selector}: {exc}")
            return False

    async def _move_mouse_to_selector(self, selector: str) -> bool:
        self.logger.info(f"Move mouse to selector start: {selector}")
        if self.use_real_mouse and await self._move_real_mouse_to_selector(selector):
            self.logger.info(f"Move mouse via real mouse succeeded: {selector}")
            return True
        rect = await self._get_rect(selector)
        if not rect:
            self.logger.info(f"Move mouse failed because rect not found: {selector}")
            return False
        x = rect["x"] + rect["width"] / 2
        y = rect["y"] + rect["height"] / 2
        actions = getattr(self.page, "actions", None)
        if actions and hasattr(actions, "move_to"):
            try:
                actions.move_to((x, y))
                await asyncio.sleep(random.uniform(0.08, 0.2))
                self.logger.info(f"Move mouse via page actions succeeded: {selector}, {self._rect_label(rect)}")
                return True
            except Exception as exc:
                self.logger.info(f"Move mouse via page actions failed selector={selector}: {exc}")
                pass
        try:
            moved = bool(self._run_js(
                """
                const sel = arguments[0];
                const x = arguments[1];
                const y = arguments[2];
                const el = document.querySelector(sel);
                if (!el) return false;
                el.dispatchEvent(new MouseEvent('mousemove', {
                    bubbles: true,
                    clientX: x,
                    clientY: y
                }));
                return true;
                """,
                selector,
                x,
                y,
            ))
            self.logger.info(f"Move mouse via JS result selector={selector}, moved={moved}, {self._rect_label(rect)}")
            return moved
        except Exception as exc:
            self.logger.info(f"Move mouse via JS failed selector={selector}: {exc}")
            return False

    async def _move_real_mouse_to_selector(self, selector: str) -> bool:
        if pyautogui is None:
            self.logger.info("Real mouse move skipped because pyautogui is unavailable.")
            return False
        point = await self._get_screen_point_for_selector(selector)
        if not point:
            self.logger.info(f"Real mouse move skipped because screen point not found: {selector}")
            return False
        focused = self._focus_browser_window()
        self.logger.info(f"Focus browser before real mouse move selector={selector}, focused={focused}")
        try:
            duration = random.uniform(0.18, 0.42)
            pyautogui.moveTo(point["x"], point["y"], duration=duration)
            await asyncio.sleep(random.uniform(0.08, 0.2))
            self.logger.info(
                f"Real mouse move succeeded selector={selector}, "
                f"screen_x={point['x']}, screen_y={point['y']}, duration={duration:.2f}"
            )
            return True
        except Exception as exc:
            self.logger.info(f"Real mouse move failed selector={selector}: {exc}")
            return False

    async def _get_screen_point_for_selector(self, selector: str) -> Optional[Dict[str, int]]:
        try:
            point = self._run_js(
                """
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                const borderX = (window.outerWidth - window.innerWidth) / 2;
                const chromeY = window.outerHeight - window.innerHeight;
                return {
                    x: Math.round(window.screenX + borderX + rect.left + rect.width / 2),
                    y: Math.round(window.screenY + chromeY + rect.top + rect.height / 2)
                };
                """,
                selector,
            )
        except Exception as exc:
            self.logger.info(f"Get screen point JS failed selector={selector}: {exc}")
            point = None
        if isinstance(point, dict) and "x" in point and "y" in point:
            try:
                self.logger.info(f"Screen point resolved selector={selector}, point={point}")
                return {"x": int(point["x"]), "y": int(point["y"])}
            except Exception:
                return None
        self.logger.info(f"Screen point resolve returned invalid data selector={selector}, point={point}")
        return None

    def _focus_browser_window(self) -> bool:
        if gw is None:
            self.logger.info("Focus browser skipped because pygetwindow is unavailable.")
            return False
        title = self._current_page_title()
        candidates: List[Any] = []
        try:
            if title:
                candidates.extend(gw.getWindowsWithTitle(title))
        except Exception:
            pass
        if not candidates:
            try:
                for keyword in ["BOSS", "直聘", "Chrome", "Google Chrome"]:
                    wins = gw.getWindowsWithTitle(keyword)
                    if wins:
                        candidates.extend(wins)
                        break
            except Exception:
                pass
        if not candidates:
            self.logger.info(f"Focus browser failed, no candidate window found, title={title}")
            return False
        window = candidates[0]
        try:
            if getattr(window, "isMinimized", False):
                window.restore()
            window.activate()
            self.logger.info(f"Browser window focused: {getattr(window, 'title', '<unknown>')}")
            return True
        except Exception as exc:
            self.logger.info(f"Focus browser failed: {exc}")
            return False

    def _current_page_title(self) -> str:
        title = getattr(self.page, "title", "")
        if callable(title):
            try:
                title = title()
            except Exception:
                title = ""
        return str(title or "").strip()

    async def _clear_input_by_js(self, selector: str) -> bool:
        try:
            ok = bool(self._run_js(
                """
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return false;
                el.focus();
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
                return true;
                """,
                selector,
            ))
            self.logger.info(f"Clear input by JS result selector={selector}, ok={ok}")
            return ok
        except Exception as exc:
            self.logger.info(f"Clear input by JS failed selector={selector}: {exc}")
            return False

    async def _dispatch_change(self, selector: str) -> bool:
        try:
            ok = bool(self._run_js(
                """
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return false;
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.blur();
                return true;
                """,
                selector,
            ))
            self.logger.info(f"Dispatch change result selector={selector}, ok={ok}")
            return ok
        except Exception as exc:
            self.logger.info(f"Dispatch change failed selector={selector}: {exc}")
            return False

    async def _get_rect(self, selector: Optional[str]) -> Optional[Dict[str, float]]:
        if not selector:
            return None
        script = """
        const sel = arguments[0];
        const el = document.querySelector(sel);
        if (!el) return null;
        const rect = el.getBoundingClientRect();
        return {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height
        };
        """
        try:
            rect = self._run_js(script, selector)
            if isinstance(rect, dict) and rect.get("width") and rect.get("height"):
                return {
                    "x": float(rect["x"]),
                    "y": float(rect["y"]),
                    "width": float(rect["width"]),
                    "height": float(rect["height"]),
                }
        except Exception:
            return None
        return None

    async def _hover_selector(self, selector: str) -> None:
        self.logger.info(f"Hover selector start: {selector}")
        moved = await self._move_mouse_to_selector(selector)
        self.logger.info(f"Hover selector move result selector={selector}, moved={moved}")
        rect = await self._get_rect(selector)
        if not rect:
            self.logger.info(f"Hover selector skipped because rect not found: {selector}")
            return
        x = rect["x"] + rect["width"] / 2
        y = rect["y"] + rect["height"] / 2
        actions = getattr(self.page, "actions", None)
        if actions and hasattr(actions, "move_to"):
            try:
                actions.move_to((x, y))
                self.logger.info(f"Hover selector via page actions succeeded: {selector}")
                return
            except Exception as exc:
                self.logger.info(f"Hover selector via page actions failed: {selector}, error={exc}")
                pass
        script = """
        const sel = arguments[0];
        const x = arguments[1];
        const y = arguments[2];
        const el = document.querySelector(sel);
        if (!el) return false;
        const evt = new MouseEvent('mousemove', {
            bubbles: true,
            clientX: x,
            clientY: y
        });
        el.dispatchEvent(evt);
        return true;
        """
        try:
            self._run_js(script, selector, x, y)
            self.logger.info(f"Hover selector via JS succeeded: {selector}")
        except Exception as exc:
            self.logger.info(f"Hover selector via JS failed: {selector}, error={exc}")
            pass

    async def _capture_region(self, rect: Optional[Dict[str, float]], output_path: Path) -> Optional[Path]:
        if Image is None:
            return None
        page_path = output_path.with_name(f"{output_path.stem}_page.png")
        if not await self._save_page_screenshot(page_path):
            return None
        if not rect:
            return page_path

        try:
            with Image.open(page_path) as img:
                dpr = await self._device_pixel_ratio()
                left = int(max(0, rect["x"] * dpr))
                top = int(max(0, rect["y"] * dpr))
                right = int(min(img.width, (rect["x"] + rect["width"]) * dpr))
                bottom = int(min(img.height, (rect["y"] + rect["height"]) * dpr))
                if right - left < 10 or bottom - top < 10:
                    return page_path
                cropped = img.crop((left, top, right, bottom))
                cropped.save(output_path)
            return output_path
        except Exception as exc:
            self.logger.info(f"Crop slider screenshot failed: {exc}")
            return page_path

    async def _save_page_screenshot(self, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Try saving page screenshot: {output_path}")
        for method_name in ("get_screenshot", "save"):
            method = getattr(self.page, method_name, None)
            if not method:
                continue
            try:
                method(path=str(output_path))
                if output_path.exists():
                    self.logger.info(f"Page screenshot saved via {method_name}: {output_path}")
                    return True
            except TypeError:
                try:
                    method(str(output_path))
                    if output_path.exists():
                        self.logger.info(f"Page screenshot saved via {method_name}: {output_path}")
                        return True
                except Exception:
                    continue
            except Exception:
                continue
        self.logger.info(f"Page screenshot save failed: {output_path}")
        return False

    async def _device_pixel_ratio(self) -> float:
        try:
            ratio = self._run_js("return window.devicePixelRatio || 1;")
            return float(ratio or 1.0)
        except Exception:
            return 1.0

    def _estimate_gap_offset(self, image_path: Path) -> Optional[float]:
        if cv2 is None:
            self.logger.info("OpenCV is unavailable, slider detection skipped.")
            return None
        image = cv2.imread(str(image_path))
        if image is None:
            return None

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        focus_height = max(40, int(gray.shape[0] * 0.72))
        roi = gray[:focus_height, :]
        blur = cv2.GaussianBlur(roi, (5, 5), 0)
        edges = cv2.Canny(blur, 80, 160)
        column_energy = edges.sum(axis=0)

        left_bound = max(10, int(len(column_energy) * 0.12))
        right_bound = max(left_bound + 1, int(len(column_energy) * 0.9))
        candidate = column_energy[left_bound:right_bound]
        if candidate.size == 0:
            return None

        best_index = int(candidate.argmax()) + left_bound
        peak_value = float(candidate.max())
        avg_value = float(candidate.mean()) if candidate.mean() else 0.0
        if peak_value < max(2500.0, avg_value * 2.0):
            return None
        return float(best_index)

    async def _drag_slider(self, handle_rect: Dict[str, float], distance: float) -> bool:
        start_x = handle_rect["x"] + handle_rect["width"] / 2
        start_y = handle_rect["y"] + handle_rect["height"] / 2
        steps = self._build_drag_steps(distance)
        actions = getattr(self.page, "actions", None)
        self.logger.info(
            f"Drag slider start_x={start_x:.1f}, start_y={start_y:.1f}, "
            f"distance={distance:.1f}, steps={len(steps)}"
        )

        if actions and hasattr(actions, "move_to"):
            try:
                actions.move_to((start_x, start_y))
                if hasattr(actions, "hold"):
                    actions.hold()
                else:
                    self.logger.info("Page actions missing hold(); fallback to JS drag.")
                    raise RuntimeError("missing hold")
                current_x = start_x
                for delta in steps:
                    current_x += delta
                    actions.move_to((current_x, start_y + random.uniform(-1.5, 1.5)))
                    await asyncio.sleep(random.uniform(0.01, 0.03))
                if hasattr(actions, "release"):
                    actions.release()
                self.logger.info("Drag slider via page actions succeeded.")
                return True
            except Exception as exc:
                self.logger.info(f"Action drag failed, fallback to JS drag: {exc}")

        return await self._drag_slider_by_js(start_x, start_y, steps)

    async def _drag_slider_by_js(self, start_x: float, start_y: float, steps: List[float]) -> bool:
        script = """
        const startX = arguments[0];
        const startY = arguments[1];
        const steps = arguments[2];
        const element = document.elementFromPoint(startX, startY);
        if (!element) return false;

        const fire = (type, x, y, target) => {
            const evt = new MouseEvent(type, {
                bubbles: true,
                cancelable: true,
                clientX: x,
                clientY: y,
                buttons: 1
            });
            target.dispatchEvent(evt);
        };

        let currentX = startX;
        fire('mousedown', currentX, startY, element);
        for (const step of steps) {
            currentX += step;
            fire('mousemove', currentX, startY, document);
        }
        fire('mouseup', currentX, startY, document);
        return true;
        """
        try:
            ok = bool(self._run_js(script, start_x, start_y, steps))
            self.logger.info(f"Drag slider via JS result ok={ok}")
            return ok
        except Exception as exc:
            self.logger.info(f"Drag slider via JS failed: {exc}")
            return False

    def _build_drag_steps(self, distance: float) -> List[float]:
        distance = max(20.0, float(distance))
        remain = distance
        steps: List[float] = []
        while remain > 0:
            if remain > distance * 0.35:
                step = random.uniform(7.0, 12.0)
            elif remain > distance * 0.1:
                step = random.uniform(3.5, 7.5)
            else:
                step = random.uniform(1.0, 3.0)
            step = min(step, remain)
            steps.append(step)
            remain -= step
        steps.extend([-random.uniform(0.5, 1.3), random.uniform(0.4, 0.9)])
        return steps
