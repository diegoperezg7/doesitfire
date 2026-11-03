"""Screenshot a page with Playwright + Chrome: url out width height color-scheme."""

import sys

from playwright.sync_api import sync_playwright

url, out, width, height, scheme = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(
        viewport={"width": width, "height": height}, color_scheme=scheme, device_scale_factor=2 if width < 500 else 1
    )
    page.goto(url)
    page.wait_for_timeout(1200)
    page.screenshot(path=out)
    browser.close()
