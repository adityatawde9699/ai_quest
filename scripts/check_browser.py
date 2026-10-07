"""Optional Chromium smoke test against a new temporary TEST database only."""
import sys
import os
import tempfile
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from app import create_app
from extensions import db
from test_event_flow import seed_content
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

with tempfile.TemporaryDirectory(prefix='aiquest-browser-') as directory:
    app=create_app({'TESTING':True,'AUTO_INIT_DB':False,'WTF_CSRF_ENABLED':False,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(Path(directory)/'test.db'),'SECRET_KEY':'test-only-browser-secret'})
    with app.app_context():db.create_all();qr1=seed_content()
    admin=app.test_client();admin.post('/admin/login',data={'username':'operator','password':'a-secure-test-password'})
    credentials=admin.post('/api/teams',json={'team_name':'Browser Test Team','member_1':'Alex','assigned_qr_id':qr1}).get_json()
    app.config['WTF_CSRF_ENABLED']=True
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_EXECUTABLE'),headless=True)
            errors=[]
            def page_for(viewport):
                context=browser.new_context(viewport=viewport)
                context.route('https://**',lambda route:route.abort())
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                return page
            operator=page_for({'width':1440,'height':1000})
            # Simulate a template cached before the new connection status markup.
            def cached_admin_template(route):
                response=route.fetch();route.fulfill(response=response,body=response.text().replace('id="connection-status"',''))
            operator.route('**/admin',cached_admin_template)
            operator.goto(base+'/admin/login',wait_until='networkidle');operator.screenshot(path='/tmp/aiquest-login-desktop.png',full_page=True);operator.locator('.password-toggle').click();assert operator.locator('[name=password]').get_attribute('type')=='text';operator.locator('.password-toggle').click();operator.locator('[name=username]').fill('operator');operator.locator('[name=password]').fill('a-secure-test-password');operator.locator('button[type=submit]').click();operator.wait_for_url('**/admin*',wait_until='domcontentloaded')
            for tab in ('teams','qrs','questions','rounds','monitoring','scores','leaderboard','results','activity','operations'):
                operator.locator(f'[data-view={tab}]').click()
            operator.locator('#create-desktop').wait_for();
            for category in ('Stations','Judging & scores','QR tools','Results & exports','Configuration','Challenges'):
                operator.get_by_role('button',name=category,exact=True).click()
                assert operator.locator('.operations-group:visible').count()==1
                assert operator.get_by_role('button',name=category,exact=True).evaluate('(n) => getComputedStyle(n).backgroundColor')=='rgb(40, 57, 173)'
            for checkbox in operator.locator('#create-quiz [name=question_ids]').all():checkbox.check()
            assert operator.locator('#quiz-selection-count').inner_text()=='10 of 10 selected'
            operator.locator('[data-view=teams]').click();operator.locator('#add-team').click()
            operator.locator('#team-form [name=team_name]').wait_for()
            operator.wait_for_function("document.activeElement.name === 'team_name'")
            operator.keyboard.press('Escape');assert operator.locator('.modal').count()==0
            assert operator.locator('#add-team').evaluate('(n) => n === document.activeElement')
            operator.set_viewport_size({'width':390,'height':844});operator.locator('#menu-toggle').click()
            assert operator.locator('#menu-toggle').get_attribute('aria-expanded')=='true'
            operator.keyboard.press('Escape');assert operator.locator('#menu-toggle').get_attribute('aria-expanded')=='false'
            assert operator.evaluate('document.documentElement.scrollWidth <= innerWidth')
            operator.set_viewport_size({'width':1440,'height':1000});operator.locator('[data-view=operations]').click();operator.locator('#create-desktop').wait_for()

            assert operator.evaluate('typeof io')=='function'
            operator.locator('#connection-status').filter(has_text='Live updates connected').wait_for()
            operator.route('**/api/admin/questions',lambda route:route.fulfill(json=[]))
            operator.locator('[data-view=operations]').click()
            operator.locator('.quiz-picker .empty-state').wait_for()
            assert operator.locator('#create-quiz button').is_disabled()
            assert operator.get_by_role('link',name='Open question bank').is_visible()
            operator.unroute('**/api/admin/questions');operator.locator('[data-view=operations]').click();operator.locator('#create-desktop').wait_for()

            operator.screenshot(path='/tmp/aiquest-admin.png',full_page=True)
            phone=page_for({'width':390,'height':844})
            def login_team(page):
                page.goto(base+'/team/login',wait_until='networkidle');assert page.evaluate('document.documentElement.scrollWidth <= innerWidth');page.screenshot(path='/tmp/aiquest-login-phone.png',full_page=True);page.locator('[name=team_id]').fill(credentials['team']['team_id']);page.locator('[name=pin]').fill(credentials['login_pin']);page.locator('button[type=submit]').click();page.wait_for_url('**/team',wait_until='domcontentloaded')
            login_team(phone)
            phone.locator('#start-round').click()
            def scan(token):
                phone.locator('#scan-fallback').evaluate('(node) => node.open = true');phone.locator('#token-input').fill(token);phone.locator('#manual-scan button').click()
            scan('round1-token');phone.locator('#team-status[data-state=ROUND_1_COMPLETED]').wait_for()
            scan('round2-token');phone.locator('#challenge-form').wait_for();assert phone.locator('#answer-progress').inner_text()=='0 of 10 answered'
            for select in phone.locator('#challenge-form select').all():select.select_option('A')
            phone.locator('#save-status').filter(has_text='All answers saved').wait_for();assert phone.locator('#answer-progress').inner_text()=='10 of 10 answered';assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.route('**/api/team/quiz/answers/**',lambda route:route.abort())
            phone.locator('#challenge-form select').first.select_option('B')
            phone.locator('#save-status').filter(has_text='Unsaved answers').wait_for()
            phone.unroute('**/api/team/quiz/answers/**')
            phone.reload(wait_until='domcontentloaded')
            phone.locator('#quiz-next').click()
            assert phone.locator('#challenge-form select').first.input_value()=='B'
            phone.locator('#challenge-form select').first.select_option('A')
            phone.locator('#save-status').filter(has_text='All answers saved').wait_for()
            phone.locator('#challenge-form button').click();phone.locator('#quiz-box').filter(has_text='Results will be announced later').wait_for()
            phone.locator('#team-status[data-state=ROUND_2_COMPLETED]').wait_for()
            assert phone.locator('#team-score').inner_text()=='Pending'
            scan('round3-token');phone.locator('#desktop-open').wait_for(state='visible');phone.screenshot(path='/tmp/aiquest-phone.png',full_page=True)
            desktop=page_for({'width':1280,'height':900});login_team(desktop);desktop.goto(base+'/desktop/1')
            for i in range(3):
                desktop.locator('#password').fill('wrong');desktop.locator('#password-form button').click();desktop.locator('#attempts').filter(has_text=f'Attempts remaining: {2-i}').wait_for()
            desktop.locator('#challenge-form').wait_for()
            for field in desktop.locator('#challenge-form textarea').all():field.fill('42');field.blur()
            desktop.locator('#save-status').filter(has_text='All answers saved').wait_for();desktop.locator('#challenge-form button').click();desktop.locator('#quiz-box').filter(has_text='Submission confirmed').wait_for();desktop.screenshot(path='/tmp/aiquest-desktop.png',full_page=True)
            assert not errors,errors
            browser.close();print('PASS: admin navigation, mobile login/QR/quiz autosave/submission, desktop three-attempt unlock and final submission, CSRF enabled; keyboard/mobile navigation, grouped operations and quiz selection, credential visibility, responsive layouts; no browser exceptions.')
    finally:
        server.shutdown()
        with app.app_context():db.session.remove();db.engine.dispose()
