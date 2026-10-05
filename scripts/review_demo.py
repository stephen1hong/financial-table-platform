"""Headless local UI demonstration; originals restored after a test correction.

Start review_app first. Requires pip install playwright and a local Chrome install.
No browser downloads or external sites are used.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT=Path('data/processed/review_demo')
OUTPUT.mkdir(parents=True,exist_ok=True)


def main():
    results={};errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1500,'height':1050},device_scale_factor=1)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8765')
        page.wait_for_selector('#existing option',state='attached')
        page.screenshot(path=str(OUTPUT/'initial.png'),full_page=True)
        def import_existing(identifier,filename):
            page.locator('#openImport').click();page.locator('#existing').select_option(identifier)
            page.locator('#importExisting').click()
            page.locator('#progressBox').wait_for(state='visible')
            page.wait_for_function("document.querySelector('#progressBox').hidden === true",timeout=180000)
            page.wait_for_function('(name)=>document.querySelector("#subtitle").textContent.startsWith(name)',arg=filename,timeout=15000)
            print('Imported',identifier,flush=True)
        import_existing('wmt-2025','wmt-20250131.htm')
        page.locator('#metric').select_option('net_sales')
        page.frame_locator('iframe').locator('table').wait_for(state='visible')
        assert '674,538' in page.frame_locator('iframe').locator('body').inner_text()
        page.screenshot(path=str(OUTPUT/'html-source.png'),full_page=True)
        automatic=page.evaluate('doc.automatic.facts.find(f=>f.table_id==="statement" && f.metric==="net_sales" && f.period.fiscal_year===2025).value')
        page.locator('#facts button').first.click()
        page.locator('#newValue').fill(str(int(automatic)+1));page.locator('#reason').fill('UI demonstration only: add one to verify recalculation, then restore the source value.')
        page.get_by_role('button',name='Save reviewed correction').click()
        page.wait_for_function('doc.revision===1')
        changed=page.evaluate('doc.reviewed_calculations.find(c=>c.table_id==="statement" && c.metric==="gross_profit" && c.period.fiscal_year===2025).value')
        assert str(changed)=='162786'
        assert page.evaluate('doc.automatic.facts.find(f=>f.table_id==="statement" && f.metric==="net_sales" && f.period.fiscal_year===2025).value')==automatic
        page.locator('button[data-tab="calculations"]').click()
        page.screenshot(path=str(OUTPUT/'recalculation.png'),full_page=True)
        page.locator('button[data-tab="facts"]').click();page.locator('#facts button').first.click()
        page.locator('#newValue').fill(str(automatic));page.locator('#reason').fill('Restore the independently checked source value after the UI demonstration.')
        page.get_by_role('button',name='Save reviewed correction').click();page.wait_for_function('doc.revision===2')
        results['html']=page.evaluate('({id:doc.id,facts:doc.automatic.facts.length,tables:doc.automatic.tables.length,revision:doc.revision,history:doc.history.length,restored:doc.reviewed_facts.find(f=>f.table_id==="statement"&&f.metric==="net_sales"&&f.period.fiscal_year===2025).value})')
        page.locator('button[data-tab="history"]').click();page.screenshot(path=str(OUTPUT/'history.png'),full_page=True)
        # Reload demonstrates the browser receives the persisted correction history.
        page.reload();page.wait_for_function('doc && doc.revision===2')
        page.locator('button[data-tab="compare"]').click()
        left=page.evaluate('doc.reviewed_facts.find(f=>f.table_id==="statement"&&f.metric==="net_sales"&&f.period.fiscal_year===2025).fact_id')
        right=page.evaluate('doc.reviewed_facts.find(f=>f.table_id==="statement"&&f.metric==="net_sales"&&f.period.fiscal_year===2024).fact_id')
        page.locator('#compareLeft').select_option(left);page.locator('#compareRight').select_option(right);page.locator('#compareButton').click()
        page.wait_for_function('document.querySelector("#comparison").textContent.includes("blocked")')
        results['incompatible_comparison']=page.locator('#comparison').inner_text()
        with page.expect_download() as download:
            page.locator('#exportJson').click()
        download.value.save_as(OUTPUT/'reviewed-export.json')
        import_existing('wmt-2025-pdf','walmartannualreport2025.pdf')
        page.locator('button[data-tab="facts"]').click();page.locator('#metric').select_option('net_sales')
        page.locator('#facts button').first.click();page.locator('#closeCorrection').click()
        page.locator('#source img').wait_for()
        page.wait_for_function('document.querySelector("#source img").complete')
        page.screenshot(path=str(OUTPUT/'pdf-source.png'),full_page=True)
        results['pdf']=page.evaluate('({id:doc.id,facts:doc.automatic.facts.length,tables:doc.automatic.tables.length,format:doc.metadata.format})')
        page.locator('#openImport').click()
        page.locator('#profile').select_option('wmt-2025')
        page.locator('#upload').set_input_files('data/processed/ocr/scans/clean-page-80.pdf')
        page.get_by_role('button',name='Upload & process').click()
        page.locator('#progressBox').wait_for(state='visible')
        page.wait_for_function('document.querySelector("#progressBox").hidden===true',timeout=180000)
        page.wait_for_function('doc && doc.metadata.format==="scanned PDF (OCR)"',timeout=15000)
        page.locator('#source img').wait_for()
        page.wait_for_function('document.querySelector("#source img").complete')
        page.screenshot(path=str(OUTPUT/'scan-upload.png'),full_page=True)
        results['scan_upload']=page.evaluate('({id:doc.id,facts:doc.automatic.facts.length,tables:doc.automatic.tables.length,format:doc.metadata.format,unresolved:doc.automatic.facts.filter(f=>f.status!=="ok").length})')
        results['browser_errors']=errors
        assert not errors,errors
        browser.close()
    (OUTPUT/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
