#!/usr/bin/env python3
"""Optional headless rendering, and the static fallback used when there is no browser.

Two rules govern this module:

  1. **Never pretend.** If no supported browser is available, the snapshot records
     `capabilities.headless_render: false`, every page gets `render: null`, and a
     `not_assessed` entry is written. A missing capability of ours is never reported as a
     defect of theirs.
  2. **Never interact.** Rendering loads a page and waits. It does not click, submit,
     scroll, dismiss, authenticate, or accept anything. A renderer that dismisses a cookie
     wall would hide the very defect the audit exists to find, and would also be a state
     change on someone else's site.

Playwright is used when it is installed. It is an optional extra, never a hard dependency:
the collector is stdlib-only and degrades to `static_spa_signals`, which detects the
highest-value failure (content that only exists after JavaScript runs) from the raw HTML
alone, at reduced confidence.
"""
import time


def detect_backend():
    """Return the name of an available rendering backend, or None. Never raises."""
    try:
        import playwright.sync_api  # noqa: F401
        return "playwright"
    except Exception:  # noqa: BLE001 - absence, import error and broken install are equal
        return None


class Renderer(object):
    """Renders pages if a backend exists. Safe to construct unconditionally."""

    def __init__(self, timeout_s=15, spa_config=None):
        self.timeout_s = timeout_s
        self.spa_config = spa_config or {}
        self.backend = detect_backend()
        self._playwright = None
        self._browser = None
        self.unavailable_reason = None
        if self.backend is None:
            self.unavailable_reason = (
                "no supported headless browser is installed in this environment")

    @property
    def available(self):
        return self.backend is not None

    def __enter__(self):
        if self.backend == "playwright":
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
            except Exception as exc:  # noqa: BLE001
                self.backend = None
                self._browser = None
                self.unavailable_reason = (
                    "a headless browser is installed but would not start: %s"
                    % str(exc)[:200])
        return self

    def __exit__(self, *exc):
        try:
            if self._browser is not None:
                self._browser.close()
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        return False

    def render(self, url, user_agent):
        """Render one URL. Returns a render dict, or None when unavailable.

        Loads and waits. Performs no interaction of any kind.
        """
        if self._browser is None:
            return None
        started = time.time()
        context = page = None
        try:
            context = self._browser.new_context(
                user_agent=user_agent, java_script_enabled=True)
            page = context.new_page()
            page.goto(url, timeout=int(self.timeout_s * 1000), wait_until="load")
            try:
                page.wait_for_load_state("networkidle",
                                         timeout=int(self.timeout_s * 1000 / 2))
            except Exception:  # noqa: BLE001 - a busy page is still worth measuring
                pass
            html = page.content()
            modals = page.evaluate(MODAL_PROBE)
            return {
                "ok": True,
                "html": html,
                "render_ms": int((time.time() - started) * 1000),
                "modal_candidates": modals or [],
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "html": None,
                    "render_ms": int((time.time() - started) * 1000),
                    "modal_candidates": [], "error": str(exc)[:200]}
        finally:
            for closable in (page, context):
                try:
                    if closable is not None:
                        closable.close()
                except Exception:  # noqa: BLE001
                    pass


# Structural overlay detection: an element that covers the viewport and sits above the
# content, or a scroll lock on the body. No keyword matching, no framework class names,
# so it works on any site in any language.
MODAL_PROBE = """
() => {
  const out = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  const bodyLocked = ['hidden', 'clip'].includes(
    getComputedStyle(document.body).overflow);
  if (bodyLocked) out.push({selector: 'body', reason: 'scroll lock on body'});
  const nodes = Array.from(document.body.querySelectorAll('*')).slice(0, 3000);
  for (const el of nodes) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    const coversViewport = r.width >= vw * 0.9 && r.height >= vh * 0.6;
    const isDialog = el.getAttribute('role') === 'dialog'
      || el.hasAttribute('aria-modal');
    if (coversViewport || (isDialog && r.width >= vw * 0.5)) {
      out.push({
        selector: el.tagName.toLowerCase()
          + (el.id ? '#' + el.id : '')
          + (el.className && typeof el.className === 'string'
             ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''),
        reason: coversViewport
          ? 'fixed element covering the viewport'
          : 'element marked as a modal dialog',
        zIndex: s.zIndex
      });
    }
    if (out.length >= 8) break;
  }
  return out;
}
"""


def static_spa_signals(parsed, config):
    """Signals that content is client-rendered, derived from the raw HTML alone.

    Used when no browser is available. Returns a list of
    `{"signal", "weight", "detail"}`. The render detector requires **two high-weight
    signals** before it will report a client-rendering failure without a browser, and
    lowers its confidence to `medium` when it does.

    Mount points are matched structurally: an element with no text content whose id or
    tag follows a common framework root convention. An unlisted convention contributes no
    signal rather than producing a wrong one.
    """
    signals = []
    thin_floor = config.get("classification", {}).get("thin_content_floor", 250)
    ratio_floor = config.get("spa_signals", {}).get("script_to_text_ratio", 20.0)

    text_len = parsed.get("main_text_len", 0)
    if text_len < thin_floor:
        signals.append({
            "signal": "empty-or-thin-main-content",
            "weight": "high",
            "detail": "main content held %d characters of text in the raw HTML, below the "
                      "%d character floor" % (text_len, thin_floor)})

    for mount in parsed.get("empty_mount_points") or []:
        signals.append({
            "signal": "empty-mount-point",
            "weight": "high",
            "detail": "element %s%s is present but contains no text"
                      % (mount["tag"], "#" + mount["id"] if mount.get("id") else "")})
        break

    if parsed.get("noscript_text"):
        signals.append({
            "signal": "noscript-notice",
            "weight": "medium",
            "detail": "the page carries a noscript notice of %d characters"
                      % len(parsed["noscript_text"])})

    script_bytes = parsed.get("script_bytes", 0)
    if text_len > 0 and script_bytes / float(max(text_len, 1)) >= ratio_floor:
        signals.append({
            "signal": "script-dominant",
            "weight": "medium",
            "detail": "inline script bytes (%d) exceed page text (%d) by more than %.0fx"
                      % (script_bytes, text_len, ratio_floor)})
    elif text_len == 0 and script_bytes > 0:
        signals.append({
            "signal": "script-dominant",
            "weight": "medium",
            "detail": "the raw HTML carries %d bytes of script and no readable text"
                      % script_bytes})

    if parsed.get("script_srcs") and text_len < thin_floor:
        signals.append({
            "signal": "external-bundle-with-no-text",
            "weight": "medium",
            "detail": "%d external scripts referenced with almost no readable text"
                      % len(parsed["script_srcs"])})

    return signals
