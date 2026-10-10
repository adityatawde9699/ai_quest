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
from models import OfflineRound3
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
            operator.locator('#create-round3').wait_for();
            for category in ('Round 3 · offline','Judging & scores','QR tools','Results & exports','Configuration','Challenges'):
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
            operator.set_viewport_size({'width':1440,'height':1000});operator.locator('[data-view=operations]').click();operator.locator('#create-round3').wait_for()

            assert operator.evaluate('typeof io')=='function'
            operator.locator('#connection-status').filter(has_text='Live updates connected').wait_for()
            operator.route('**/api/admin/questions',lambda route:route.fulfill(json=[]))
            operator.locator('[data-view=operations]').click()
            operator.locator('.quiz-picker .empty-state').wait_for()
            assert operator.locator('#create-quiz button').is_disabled()
            assert operator.get_by_role('link',name='Open question bank').is_visible()
            operator.unroute('**/api/admin/questions');operator.locator('[data-view=operations]').click();operator.locator('#create-round3').wait_for()

            operator.locator('[data-view=qrs]').click()
            operator.locator('#add-qr').click()
            operator.locator('#qr-form [name=round_id]').select_option('3')
            operator.locator('#qr-form [name=team_id]').select_option(str(credentials['team']['id']))
            for name,value in {'title':'Team password riddle','clue':'The answer to life','password':'forty-two','max_points':'100','expiry_date':'2030-01-01','expiry_time':'12:00'}.items():
                operator.locator(f'#qr-form [name={name}]').fill(value)
            operator.locator('#qr-submit').click()
            operator.locator('#qr-form').wait_for(state='detached')
            operator.locator('#modal-root img').wait_for()
            operator.locator('.modal-close').click()
            operator.locator('[data-view=operations]').click()
            operator.get_by_role('button',name='Round 3 · offline',exact=True).click()
            operator.locator('#ops-round3 details').wait_for()
            operator.locator('#ops-round3 summary').click()
            operator.locator('[data-r3-action=activate]').click()
            operator.locator('#ops-round3').filter(has_text='ACTIVE').wait_for()
            with app.app_context():
                config=OfflineRound3.query.one()
                config_id=config.id
                password_token=config.password_qr.secure_token

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
            scan(password_token);phone.locator('#round3-password-form').wait_for(state='visible')
            phone.locator('#round3-password').fill('wrong');phone.locator('#round3-password-form button').click()
            phone.locator('#round3-attempts').filter(has_text='2').wait_for()
            phone.locator('#round3-password').fill('forty-two');phone.locator('#round3-password-form button').click()
            phone.locator('#round3-status').filter(has_text='Password accepted').wait_for()
            assert phone.locator('#round3-password-form').is_hidden()
            phone.reload(wait_until='domcontentloaded')
            phone.locator('#round3-status').filter(has_text='Password accepted').wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path='/tmp/aiquest-phone.png',full_page=True)
            phone.on('dialog',lambda dialog:dialog.accept())
            phone.locator('#complete-round3').click()
            phone.locator('#team-status[data-state=COMPLETED]').wait_for()
            saved_time=phone.locator('#team-elapsed').inner_text()
            phone.wait_for_timeout(1200)
            assert phone.locator('#team-elapsed').inner_text()==saved_time
            phone.reload(wait_until='domcontentloaded')
            phone.locator('#team-status[data-state=COMPLETED]').wait_for()
            assert phone.locator('#team-elapsed').inner_text()==saved_time
            assert phone.locator('#complete-round3').is_hidden()
            operator.locator('[data-view=operations]').click()
            operator.get_by_role('button',name='Round 3 · offline',exact=True).click()
            operator.locator('#ops-round3 summary').click()
            operator.locator('[data-r3-sheet] button').click()
            operator.locator('[data-r3-action=submit]').wait_for(state='attached')
            operator.locator('#ops-round3 summary').click()
            operator.locator('[data-r3-action=submit]').click()
            operator.locator('#ops-round3').filter(has_text='Paper submitted').wait_for()
            operator.get_by_role('button',name='Judging & scores',exact=True).click()
            operator.locator('[data-r3-review] [name=points]').fill('75')
            operator.locator('[data-r3-review] [name=reason]').fill('Paper evaluated by organizer')
            operator.evaluate('window.refreshRound3Monitor()')
            assert operator.locator('[data-r3-review] [name=reason]').input_value()=='Paper evaluated by organizer'
            operator.locator('[data-r3-review] button').click()
            operator.locator('[data-r3-review]').filter(has_text='Reviewed').wait_for()
            phone.reload(wait_until='domcontentloaded')
            phone.locator('#team-status[data-state=COMPLETED]').wait_for()
            phone.locator('#round3-status').filter(has_text='paper submission is recorded').wait_for()
            assert phone.locator('#team-score').inner_text()=='Pending'
            assert phone.locator('#desktop-open').count()==0
            with app.app_context():
                assert OfflineRound3.query.one().points==75
            assert not errors,errors
            browser.close();print('PASS: admin navigation, mobile login/QR/quiz autosave/submission, phone password verification, one password riddle QR, organizer sheet collection/return and manual scoring, CSRF enabled; keyboard/mobile navigation, grouped operations and quiz selection, credential visibility, responsive layouts; no browser exceptions.')
    finally:
        server.shutdown()
        with app.app_context():db.session.remove();db.engine.dispose()
