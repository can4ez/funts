"""Run with: python tests/browser_smoke.py (requires Playwright + Chromium)"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    # set_content avoids file:// restrictions in sandboxed test runners
    page.set_content((ROOT / 'index.html').read_text(encoding='utf-8'), wait_until='load')
    assert page.locator('[data-player]').count() == 4
    assert page.locator('[data-mode="teams"]').is_enabled()
    for i in range(2):
        page.click('#addPlayerButton')
    assert page.locator('[data-player]').count() == 6
    page.click('[data-mode="teams"]')
    assert 'selected' in page.locator('[data-mode="teams"]').get_attribute('class')
    page.locator('#adultCheck').check()
    page.click('#startButton')
    assert page.locator('#playerStrip .player-pill').count() == 6
    assert page.locator('#roundMeter i').count() == 6
    assert '3 × 3' in page.locator('#gameModeLabel').inner_text()
    seen = []
    for _ in range(6):
        seen.append(page.locator('#currentName').inner_text())
        page.click('#truthButton')
        assert page.locator('#cardPrompt').inner_text()
        page.click('#completeButton')
    assert len(set(seen)) == 6, seen
    assert 'РАУНД 02' in page.locator('#roundNumber').inner_text()
    page.screenshot(path=str(ROOT / 'preview-six-players.png'), full_page=True)
    page.click('#finishButton')
    assert page.locator('#summaryList .summary-row').count() == 6
    page.click('#restartButton')
    assert page.locator('[data-player]').count() == 6
    page.click('[data-remove-player="5"]')
    assert page.locator('[data-player]').count() == 5
    assert page.locator('[data-mode="teams"]').is_disabled()
    for _ in range(19):
        page.click('#addPlayerButton')
    assert page.locator('[data-player]').count() == 24
    assert page.locator('#addPlayerButton').is_disabled()
    page.locator('#adultCheck').check()
    page.click('#startButton')
    assert page.locator('#playerStrip .player-pill').count() == 24
    assert page.locator('.orbit-person').count() == 8
    assert page.locator('#roundMeter i').count() == 24
    page.screenshot(path=str(ROOT / 'preview-24-players.png'), full_page=True)
    # Verify mobile layout for many players.
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(ROOT / 'preview-mobile-many-players.png'), full_page=True)
    doc_width = page.evaluate('document.documentElement.scrollWidth')
    assert doc_width <= 392, f'mobile overflow {doc_width}'
    # Import a local JSON bank and ensure no duplicate import.
    page.click('#settingsButton')
    page.click('#customInGame')
    f = str(ROOT / 'examples/clean-question-bank.json')
    page.locator('#importFile').set_input_files(f)
    page.wait_for_timeout(250)
    count_text = page.locator('#customTotal').inner_text()
    assert '7' in count_text, count_text
    page.locator('#importFile').set_input_files(f)
    page.wait_for_timeout(250)
    count_text2 = page.locator('#customTotal').inner_text()
    assert count_text2 == count_text, (count_text,count_text2)
    page.click('[data-close="customOverlay"]')
    page.click('#settingsButton')
    page.click('#resetToSetup')
    for i in range(23, 1, -1):
        page.click(f'[data-remove-player="{i}"]')
    assert page.locator('[data-player]').count() == 2
    assert page.locator('[data-remove-player]').count() == 0
    assert page.locator('[data-mode="teams"]').is_disabled()
    page.click('[data-mode="chaos"]')
    page.locator('#adultCheck').check()
    page.click('#startButton')
    assert page.locator('#roundMeter i').count() == 2
    for _ in range(2):
        page.click('#truthButton')
        page.click('#completeButton')
    assert 'РАУНД 02' in page.locator('#roundNumber').inner_text()
    assert not page.locator('#eventOverlay').evaluate('(el) => el.classList.contains("hidden")')
    page.click('#eventCloseButton')
    assert not errors, errors
    print('Browser smoke tests: PASS; 2/6/24 players, teams, chaos, mobile, JSON import, dedup')
    browser.close()
