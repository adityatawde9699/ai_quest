"""Independent connections race on an isolated on-disk database."""
import tempfile
import os
import uuid
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from app import create_app
from extensions import db
from models import ActivityLog, Batch, Desktop, DesktopSession, FinalAssignment, PasswordAttempt, QRChallenge, QuizAttempt, Score
import test_event_flow as flow


class RaceTests(unittest.TestCase):
    new_team=flow.EventFlowTests.new_team
    round1=flow.EventFlowTests.round1
    quiz=flow.EventFlowTests.quiz
    desktop=flow.EventFlowTests.desktop
    scan=flow.EventFlowTests.scan

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='aiquest-race-')
        uri='sqlite:///'+str(Path(self.directory.name)/'test.db')
        self.schema=None
        self.postgres=os.getenv('RACE_DATABASE_URL')
        options={}
        if self.postgres:
            import psycopg
            from psycopg import sql
            self.schema='aiquest_race_'+uuid.uuid4().hex
            with psycopg.connect(self.postgres) as connection:
                connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
            uri=self.postgres.replace('postgresql://','postgresql+psycopg://')
            options={'connect_args':{'options':f'-csearch_path={self.schema}'}}
        self.app=create_app({'TESTING':True,'APP_ENV':'development','EVENT_MODE':'TEST','AUTO_INIT_DB':False,'WTF_CSRF_ENABLED':False,
                             'SQLALCHEMY_DATABASE_URI':uri,'SQLALCHEMY_ENGINE_OPTIONS':options,'SECRET_KEY':'test-secret'})
        with self.app.app_context():db.create_all();self.qr1=flow.seed_content()
        self.admin=self.app.test_client();self.admin.post('/admin/login',data={'username':'operator','password':'a-secure-test-password'})
        self.team,self.credentials=self.new_team()

    def tearDown(self):
        with self.app.app_context():db.session.remove();db.engine.dispose()
        self.directory.cleanup()
        if self.schema:
            import psycopg
            from psycopg import sql
            with psycopg.connect(self.postgres) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def race(self,path,payload,count=12):
        cookie=self.team.get_cookie('session').value
        def action(_):
            client=self.app.test_client();client.set_cookie('session',cookie)
            return client.post(path,json=payload).status_code
        with ThreadPoolExecutor(max_workers=count) as pool:return list(pool.map(action,range(count)))

    def test_simultaneous_passwords_never_exceed_three(self):
        self.desktop()
        statuses=self.race('/api/team/desktop/password',{'password':'wrong'})
        self.assertEqual(statuses.count(200),3,statuses)
        self.assertEqual(statuses.count(409),9,statuses)
        with self.app.app_context():
            self.assertEqual(DesktopSession.query.one().password_attempts,3)
            self.assertEqual(PasswordAttempt.query.count(),3)
            self.assertEqual(FinalAssignment.query.count(),1)

    def test_simultaneous_quiz_submissions_score_once(self):
        self.round1();self.scan('round2-token')
        for q in self.team.get('/api/team/quiz').get_json()['questions']:
            self.team.put(f"/api/team/quiz/answers/{q['id']}",json={'answer':'A'})
        statuses=self.race('/api/team/quiz/submit',{})
        self.assertEqual(statuses.count(200),1,statuses)
        self.assertEqual(statuses.count(409),11,statuses)
        with self.app.app_context():
            self.assertEqual(QuizAttempt.query.count(),1)
            self.assertEqual(QuizAttempt.query.one().score,20)
            self.assertEqual(Score.query.filter_by(round_id=2).one().points,20)

    def test_simultaneous_scans_advance_once(self):
        self.team.post('/api/team/rounds/1/start',json={})
        statuses=self.race('/api/team/scan',{'token':'round1-token'})
        self.assertEqual(statuses.count(200),1,statuses)
        self.assertEqual(statuses.count(409),11,statuses)
        with self.app.app_context():self.assertEqual(Score.query.filter_by(round_id=1).one().points,20)

    def test_simultaneous_round_three_entries_release_one_batch(self):
        other,_=self.new_team()
        for _ in range(4):self.new_team()
        with self.app.app_context():
            qr=QRChallenge(qr_id='DESKTOP-QR-2',secure_token='round3-token-2',round_id=3,status='ACTIVE')
            db.session.add(qr);db.session.flush()
            desktop=Desktop(name='DESKTOP-02',qr_id=qr.id)
            desktop.set_password('forty-two')
            db.session.add(desktop);db.session.commit()
        self.quiz(self.team);self.quiz(other)
        def scan(pair):
            client,token=pair
            return client.post('/api/team/scan',json={'token':token}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(scan,[(self.team,'round3-token'),(other,'round3-token-2')]))
        self.assertEqual(statuses,[200,200])
        with self.app.app_context():
            self.assertEqual(Batch.query.filter_by(number=2).one().status,'RELEASED')
            self.assertEqual(ActivityLog.query.filter_by(action='BATCH_RELEASED',target='2').count(),1)
