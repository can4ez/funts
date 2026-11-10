"""Optional interactive responsive smoke test (Playwright + Chromium).

Run locally:
    pip install playwright
    python -m playwright install chromium
    python tests/responsive_qa.py

Checks setup, game and five dialogs at narrow/mobile/tablet/desktop widths,
plus focus management, import and on-screen-keyboard viewport positioning.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'index.html').read_text(encoding='utf-8')
SIZES = [(320, 568), (360, 640), (375, 667), (390, 844),
         (430, 932), (667, 375), (768, 1024), (1024, 768), (1440, 900)]


def measure(page):
    return page.evaluate('''() => {
      const modal = document.querySelector('.overlay:not(.hidden) .dialog');
      const overlay = document.querySelector('.overlay:not(.hidden)');
      const r = el => {if (!el) return null; const t = el.getBoundingClientRect();
        return {x:t.x,y:t.y,right:t.right,bottom:t.bottom,width:t.width,height:t.height}};
      return {innerWidth,innerHeight,docWidth:document.documentElement.scrollWidth,
        bodyWidth:document.body.scrollWidth,modal:r(modal),overlay:r(overlay),
        close:r(overlay?.querySelector('.close-button'))};
    }''')


def assert_fit(page, label):
    m = measure(page)
    assert m['docWidth'] <= m['innerWidth'] + 1, (label, m)
    assert m['bodyWidth'] <= m['innerWidth'] + 1, (label, m)
    if m['modal']:
        assert m['modal']['x'] >= -1 and m['modal']['right'] <= m['innerWidth']+1, (label,m)
        assert m['modal']['y'] >= -1 and m['modal']['bottom'] <= m['innerHeight']+1, (label,m)
        assert m['close']['width'] >= 44 and m['close']['height'] >= 44, (label,m)


with sync_playwright() as p:
    launch = {'headless': True, 'args': ['--no-sandbox']}
    if Path('/usr/bin/chromium').exists():
        launch['executable_path'] = '/usr/bin/chromium'
    browser = p.chromium.launch(**launch)
    for width, height in SIZES:
        page = browser.new_page(viewport={'width': width, 'height': height},
                                is_mobile=width <= 800, has_touch=width <= 800)
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.set_content(HTML, wait_until='load')
        assert_fit(page, f'setup {width}x{height}')
        page.locator('#customOpen').click()
        assert_fit(page, f'custom dialog {width}x{height}')
        assert page.locator('#customTouchRow').is_hidden(), 'Truth must not offer touch actions'
        if width <= 600:
            button = page.locator('#importFile').locator('xpath=preceding-sibling::label')
            export = page.locator('#exportCardsButton')
            for el in (button, export):
                dimensions = el.bounding_box()
                assert dimensions and dimensions['height'] >= 44, (width, dimensions)
        if (width, height) == (320, 568):
            add = page.locator('#addCustomButton').bounding_box()
            assert add and add['y'] + add['height'] <= height + 1, add
        if width == 768:
            assert measure(page)['modal']['width'] <= 620, 'Tablet sheet should not span entire screen'
        # Make sure long content scrolls inside the modal, retaining a usable close button.
        page.locator('#customOverlay .dialog').evaluate('(el) => {el.scrollTop = el.scrollHeight;}')
        top = page.locator('#customOverlay .close-button').bounding_box()
        assert top and top['y'] >= 0 and top['y'] + top['height'] <= height, (width,top)
        # Import/export must be reachable by scrolling, even on very short screens.
        page.locator('#exportCardsButton').scroll_into_view_if_needed()
        assert page.locator('#exportCardsButton').is_visible()
        assert_fit(page, f'scrolled dialog {width}x{height}')
        # Focus returns to the button used to open the modal.
        page.keyboard.press('Escape')
        assert page.locator('#customOverlay').is_hidden()
        assert page.evaluate('document.activeElement.id') == 'customOpen'
        assert not page.locator('body').evaluate('(el)=>el.classList.contains("modal-open")')
        assert not errors, (width, errors)
        page.close()

    page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    page.set_content(HTML)
    page.locator('#customOpen').click()
    assert page.evaluate('document.activeElement.classList.contains("close-button")')
    page.keyboard.press('Shift+Tab')
    assert page.evaluate('document.activeElement.id') == 'exportCardsButton', 'Reverse focus trap'
    page.keyboard.press('Tab')
    assert page.evaluate('document.activeElement.classList.contains("close-button")'), 'Forward focus trap'
    page.locator('#customType').select_option('dare')
    assert page.locator('#customTouchRow').is_visible()
    page.locator('#customTouch').check()
    page.locator('#customType').select_option('truth')
    assert page.locator('#customTouchRow').is_hidden()
    assert not page.locator('#customTouch').is_checked()
    answer = 'Какая поездка оставила самые яркие воспоминания?'
    page.locator('#customText').fill(answer)
    assert page.locator('#customTextCount').inner_text() == f'{len(answer)} / 250'
    page.locator('#addCustomButton').click()
    assert '1 шт.' in page.locator('#customTotal').inner_text()
    assert page.locator('#customTextCount').inner_text() == '0 / 250'
    # Keyboard interaction triggers the hidden file input (without a flaky OS picker).
    page.evaluate('''() => {window._fileInputActivated=false; document.getElementById('importFile').click=()=>{window._fileInputActivated=true;};}''')
    page.locator('.file-import').focus()
    page.keyboard.press('Enter')
    assert page.evaluate('window._fileInputActivated'), 'Keyboard must activate upload control'
    page.locator('#importFile').set_input_files(str(ROOT / 'examples/clean-question-bank.json'))
    assert '8 шт.' in page.locator('#customTotal').inner_text()
    # Make keyboard's visual viewport smaller; overlay must remain inside it.
    page.evaluate('''() => {
      Object.defineProperty(window, 'visualViewport', { configurable: true,
        value: {height:380,offsetTop:34,addEventListener(){} } });
      window.dispatchEvent(new Event('resize'));
    }''')
    bounds = page.locator('#customOverlay').bounding_box()
    assert bounds and abs(bounds['y'] - 34) <= 1 and abs(bounds['height'] - 380) <= 1, bounds
    page.locator('#customOverlay .close-button').click()
    page.close()

    # Very long player names and settings/summary dialogs must not overflow.
    page = browser.new_page(viewport={'width': 320, 'height': 568}, is_mobile=True, has_touch=True)
    page.set_content(HTML)
    for _ in range(5):
        page.locator('#addFourPlayersButton').click()
    assert page.locator('[data-player]').count() == 24
    page.locator('[data-player="0"]').fill('Очень-длинное-имя-участника-без-пробелов-' * 3)
    page.locator('#adultCheck').check()
    page.locator('#startButton').click()
    assert_fit(page, '24-player game')
    page.locator('#mobilePlayersButton').click()
    assert_fit(page, '24-player scores')
    page.locator('#playersOverlay .dialog').evaluate('(el)=>el.scrollTop=el.scrollHeight')
    assert page.locator('#playersOverlay .close-button').bounding_box()['y'] >= 0
    page.locator('#playersOverlay .close-button').click()
    page.locator('#settingsButton').click()
    assert_fit(page, 'settings dialog')
    page.locator('#settingsOverlay .close-button').click()
    page.locator('#eventButton').click()
    assert_fit(page, 'event dialog')
    page.locator('#eventCloseButton').click()
    page.locator('#finishButton').click()
    assert_fit(page, 'summary dialog')
    browser.close()

print('Responsive QA: PASS — 9 viewport sizes, modal scrolling, touch targets, keyboard, import and 24 players')
