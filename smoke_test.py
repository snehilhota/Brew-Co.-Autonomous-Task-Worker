"""Check project dependencies and a minimal Playwright/Chromium run."""

import flask
import httpx
import pydantic
import pytest
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


def main() -> None:
    # Loading is safe when .env is absent; it simply leaves the environment alone.
    load_dotenv()

    # Playwright owns the browser process inside this context and closes it on exit.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<h1>Brew and Co.</h1>")
        heading = page.locator("h1").inner_text()
        browser.close()

    assert heading == "Brew and Co.", f"Unexpected page heading: {heading!r}"
    print("SMOKE TEST PASSED!")


if __name__ == "__main__":
    main()
