"""A small, origin-restricted Playwright session with text observations."""

from urllib.parse import unquote, urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


class BrowserSession:
    def __init__(self, base_url: str, timeout_ms: int = 15000):
        self.base_url = base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("The browser environment must use local HTTP (localhost or a loopback IP).")
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self.elements: dict[str, str] = {}
        self.last_action_status: int | None = None

    def start(self) -> None:
        if self.page is not None:
            return
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(accept_downloads=False)
        self._context.route("**/*", self._guard_request)
        self.page = self._context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.page.on("download", lambda download: download.cancel())
        self.page.on("response", self._remember_navigation_response)

    def _remember_navigation_response(self, response) -> None:
        if response.request.is_navigation_request():
            self.last_action_status = response.status

    def _guard_request(self, route) -> None:
        parsed = urlparse(route.request.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin != self.origin or unquote(parsed.path).startswith("/__"):
            route.abort()
        else:
            route.continue_()

    def close(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self.page = None

    def resolve_url(self, url: str) -> str:
        resolved = urljoin(self.base_url + "/", url)
        parsed = urlparse(resolved)
        if f"{parsed.scheme}://{parsed.netloc}" != self.origin:
            raise ValueError("Browser navigation is restricted to the configured environment origin.")
        if unquote(parsed.path).startswith("/__"):
            raise ValueError("Harness-only paths are blocked by the browser tool.")
        return resolved

    def open(self, url: str) -> str:
        self.start()
        assert self.page is not None
        self.page.goto(self.resolve_url(url), wait_until="domcontentloaded")
        return self.observe()

    def observe(self) -> str:
        self.start()
        assert self.page is not None
        page = self.page
        self.elements = {}
        controls = page.locator("a, button, input, select, textarea").evaluate_all(
            """els => els.filter(el => !el.closest('[hidden]') && el.getAttribute('type') !== 'hidden')
                .map((el, index) => {
                const id = String(index + 1);
                el.setAttribute('data-agent-element-id', id);
                const tag = el.tagName.toLowerCase();
                const label = el.labels && el.labels.length
                    ? el.labels[0].innerText.trim() : (el.getAttribute('aria-label') || '');
                const text = (el.innerText || el.value || el.getAttribute('placeholder') || '').trim();
                const options = tag === 'select'
                    ? Array.from(el.options).map(o => o.text.trim()).join(' | ') : '';
                return {id, tag, domId: el.id || '', label, text, options,
                    risk: el.dataset.risk || '', action: el.dataset.action || '',
                    amount: el.dataset.amount || ''};
            })"""
        )
        lines = []
        for control in controls:
            element_id = control["id"]
            selector = f'[data-agent-element-id="{element_id}"]'
            self.elements[element_id] = selector
            details = [f'[{element_id}] {control["tag"]}']
            if control["domId"]:
                details.append(f'#{control["domId"]}')
            if control["label"]:
                details.append(f'label="{control["label"][:100]}"')
            if control["text"]:
                details.append(f'value="{control["text"][:160]}"')
            if control["options"]:
                details.append(f'options=[{control["options"][:400]}]')
            if control["risk"]:
                details.append(f'risk={control["risk"]}')
            if control["action"]:
                details.append(f'action={control["action"]}')
            if control["amount"]:
                details.append(f'amount={control["amount"]}')
            lines.append(" ".join(details))

        visible_text = page.locator("body").inner_text()[:4000]
        errors = page.locator("#form-errors").inner_text() if page.locator("#form-errors").count() else ""
        return (
            f"URL: {page.url}\nTITLE: {page.title()}\nTEXT: {visible_text}\n"
            f"ELEMENTS:\n" + "\n".join(lines) + f"\nERRORS: {errors[:1000]}"
        )[:6500]

    def selector_for(self, element_id: str) -> str:
        if element_id not in self.elements:
            raise ValueError("Unknown or stale element_id; observe the page again first.")
        return self.elements[element_id]

    def target_metadata(self, element_id: str) -> dict[str, str | int | None]:
        assert self.page is not None
        selector = self.selector_for(element_id)
        values = self.page.locator(selector).evaluate(
            "el => ({risk: el.dataset.risk || '', action: el.dataset.action || null, "
            "amount: el.dataset.amount || null, tag: el.tagName.toLowerCase()})"
        )
        amount = int(values["amount"]) if str(values.get("amount", "")).isdigit() else None
        return {**values, "amount": amount}

    def click(self, element_id: str) -> str:
        assert self.page is not None
        self.last_action_status = None
        self.page.locator(self.selector_for(element_id)).click()
        return self.observe()

    def type_text(self, element_id: str, text: str, clear: bool = True) -> str:
        assert self.page is not None
        locator = self.page.locator(self.selector_for(element_id))
        if clear:
            locator.fill(text)
        else:
            locator.press_sequentially(text)
        return self.observe()

    def select(self, element_id: str, option: str) -> str:
        assert self.page is not None
        self.page.locator(self.selector_for(element_id)).select_option(label=option)
        return self.observe()

    def screenshot(self, path: str) -> str:
        assert self.page is not None
        self.page.screenshot(path=path, full_page=True)
        return path

