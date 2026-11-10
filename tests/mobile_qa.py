from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf8')

def overflow(page, label):
    sizes=page.evaluate('''() => ({viewport:innerWidth,root:document.documentElement.scrollWidth,body:document.body.scrollWidth})''')
    assert sizes['root'] <= sizes['viewport'],(label,sizes)
    assert sizes['body'] <= sizes['viewport'],(label,sizes)
    print(label,'width',sizes)

def shot(page,name):
    page.screenshot(path=str(ROOT/name),full_page=True)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
    for width,height in [(390,844),(320,700),(430,932)]:
        page=browser.new_page(viewport={'width':width,'height':height}, device_scale_factor=1, is_mobile=True, has_touch=True)
        errors=[]
        page.on('pageerror', lambda e:errors.append(str(e)))
        page.set_content(html,wait_until='load')
        assert page.locator('[data-player]').count()==4
        overflow(page,f'setup_{width}')
        if width==390: shot(page,'mobile-v3-setup.png')
        page.locator('#addFourPlayersButton').click()
        assert page.locator('[data-player]').count()==8
        page.locator('#adultCheck').check()
        page.locator('#startButton').click()
        assert page.locator('#playerStrip .player-pill').count()==8
        assert page.locator('#mobileTurnName').inner_text()
        assert page.locator('#mobilePlayersCount').inner_text()=='8'
        overflow(page, f'game-choice_{width}')
        if width==390: shot(page,'mobile-v3-choice.png')
        page.locator('#mobilePlayersButton').click()
        assert not page.locator('#playersOverlay').evaluate('(el)=>el.classList.contains("hidden")')
        assert page.locator('#playersSheetList .sheet-player').count()==8
        overflow(page,f'sheet_{width}')
        if width==390: shot(page,'mobile-v3-players.png')
        page.locator('[data-close="playersOverlay"]').click()
        page.locator('#dareButton').click()
        assert page.locator('#cardPrompt').inner_text()
        assert page.locator('#completeButton').is_visible()
        overflow(page,f'game-card_{width}')
        if width==390: shot(page,'mobile-v3-card.png')
        page.locator('#redrawButton').click()
        assert page.locator('#cardPrompt').inner_text()
        page.locator('#timerButton').click()
        assert 'сек.' in page.locator('#timerButton').inner_text()
        page.locator('#skipButton').click()
        assert page.locator('#choosePanel').is_visible()
        assert 'Ход 2 из 8'==page.locator('#mobileProgressText').inner_text()
        assert page.locator('#mobileTurnName').inner_text()
        overflow(page,f'game-next_{width}')
        assert not errors,errors
        page.close()
    # Examine long text and 24 players with 320px screen
    page=browser.new_page(viewport={'width':320,'height':640},is_mobile=True,has_touch=True)
    page.set_content(html)
    for _ in range(5):page.locator('#addFourPlayersButton').click()
    assert page.locator('[data-player]').count()==24
    page.locator('#adultCheck').check();page.locator('#startButton').click()
    page.locator('#truthButton').click()
    page.evaluate('''() => {state.game.activeCard.text='Расскажи о самом неожиданном моменте своей жизни, когда пришлось сделать сложный выбор, объясни, что на тебя повлияло, чего ты опасался и как поступил бы сейчас, если бы оказался в похожей ситуации?';renderGame();}''')
    assert 'long-copy' in page.locator('#cardPanel').get_attribute('class')
    overflow(page,'very-narrow-long-prompt')
    shot(page,'mobile-v3-long-question.png')
    browser.close()
print('Mobile QA: PASS')
