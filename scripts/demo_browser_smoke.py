"""Optional developer UI smoke; requires Playwright and locally installed Chrome.

Start review_app with the offline demo database first. No browser download.
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:8765')
    args=p.parse_args()
    with sync_playwright() as driver:
        browser=driver.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url)
        page.wait_for_selector('#facts button')
        assert page.locator('#facts').inner_text().count('USD (millions)') == 3
        page.locator('#facts button').first.click()
        page.locator('#correctionDialog').wait_for(state='visible')
        page.locator('#closeCorrection').click()
        Path('data/processed/demo').mkdir(parents=True,exist_ok=True)
        page.screenshot(path='data/processed/demo/browser.png',full_page=True)
        assert not errors,errors
        browser.close()
    print('Synthetic demo browser smoke passed; no JavaScript errors')


if __name__=='__main__':main()
