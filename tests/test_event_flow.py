"""Critical event flows and security boundaries against isolated databases."""
import unittest
from datetime import timedelta
from app import create_app
from extensions import db, socketio
from models import (OfflineRound3, ActivityLog, Admin, Answer, Batch, Desktop, DesktopSession, Event, FinalAnswer,
                    FinalAssignment, PasswordAttempt, QRChallenge, QRScanEvent, Question,
                    Quiz, QuizAttempt, QuizQuestion, Round, RoundSession, Score, Team, utcnow)
from routes.common import emit_leaderboard


def seed_content():
    event=db.session.get(Event,1)
    if not event:
        event=Event(id=1)
        db.session.add(event)
    event.active,event.final_question_count,event.round_1_points=True,3,20
    db.session.add_all([Round(id=n,number=n,name=f"Round {n}",status="ACTIVE") for n in (1,2,3)])
    admin=Admin(username="operator",role="super-admin")
    admin.set_password("a-secure-test-password")
    normal=Admin(username="judge",role="admin")
    normal.set_password("a-secure-test-password")
    db.session.add_all([admin,normal])
    db.session.flush()
    quiz=Quiz(title="Destination quiz")
    db.session.add(quiz)
    db.session.flush()
    for i in range(10):
        q=Question(round_id=2,prompt=f"Quiz {i}",correct_answer="A",points=2,
                   option_a="Choice A",option_b="Choice B",option_c="Choice C",option_d="Choice D")
        db.session.add(q)
        db.session.flush()
        db.session.add(QuizQuestion(quiz_id=quiz.id,question_id=q.id,position=i))
    for i in range(12):
        db.session.add(Question(round_id=3,prompt=f"Final {i}",kind="NUMERICAL",correct_answer="42",points=5))
    qr1=QRChallenge(qr_id="QR-07",secure_token="round1-token",round_id=1,
                    clue="Many pages, quiet shelves",room="Library",status="ACTIVE")
    qr2=QRChallenge(qr_id="QR-LIBRARY",secure_token="round2-token",round_id=2,
                    quiz_id=quiz.id,room="Library",status="ACTIVE")
    db.session.add_all([qr1,qr2]);db.session.commit()
    return qr1.id


class EventFlowTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app({"TESTING":True,"APP_ENV":"development","EVENT_MODE":"TEST","AUTO_INIT_DB":False,"WTF_CSRF_ENABLED":False,
                             "SQLALCHEMY_DATABASE_URI":"sqlite:///:memory:","SECRET_KEY":"test-secret"})
        with self.app.app_context():
            db.create_all();self.qr1=seed_content()
        self.admin=self.app.test_client()
        self.admin.post('/admin/login',data={'username':'operator','password':'a-secure-test-password'})
        self.team,self.credentials=self.new_team()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove();db.drop_all();db.engine.dispose()

    def new_team(self):
        response=self.admin.post('/api/teams',json={'team_name':'Neural Knights','member_1':'Alex','assigned_qr_id':self.qr1})
        self.assertEqual(response.status_code,201,response.get_json())
        credentials=response.get_json()
        client=self.app.test_client()
        result=client.post('/team/login',data={'team_id':credentials['team']['team_id'],'pin':credentials['login_pin']})
        self.assertEqual(result.status_code,302)
        return client,credentials

    def scan(self,token,client=None):
        return (client or self.team).post('/api/team/scan',json={'token':token})

    def test_expired_qr_rejects_scan_and_logs_reason(self):
        with self.app.app_context():
            qr=db.session.get(QRChallenge,self.qr1)
            qr.expires_at=utcnow()-timedelta(seconds=1)
            db.session.commit()
        self.team.post('/api/team/rounds/1/start',json={})
        response=self.scan('round1-token')
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.get_json()['status'],'EXPIRED')
        self.assertIn('QR EXPIRED',response.get_json()['error'])
        with self.app.app_context():
            self.assertEqual(QRScanEvent.query.filter_by(status='EXPIRED').count(),1)

    def round1(self,client=None):
        client=client or self.team
        self.assertEqual(client.post('/api/team/rounds/1/start',json={}).status_code,200)
        self.assertEqual(self.scan('round1-token',client).status_code,200)

    def quiz(self,client=None):
        client=client or self.team
        self.round1(client)
        self.assertEqual(self.scan('round2-token',client).status_code,200)
        questions=client.get('/api/team/quiz').get_json()['questions']
        for q in questions:
            self.assertEqual(client.put(f"/api/team/quiz/answers/{q['id']}",json={'answer':'A'}).status_code,200)
        self.assertEqual(client.post('/api/team/quiz/submit',json={}).status_code,200)
        return questions

    def configure_round3(self, client=None, token='round3-token'):
        client = client or self.team
        team_id = client.get('/api/team/dashboard').get_json()['team']['id']
        created = self.admin.post('/api/admin/round3', json={
            'team_id': team_id, 'password_clue': 'The answer to life', 'password': 'forty-two',
'room': 'Library', 'max_points': 100})
        self.assertEqual(created.status_code, 201, created.get_json())
        config = created.get_json()
        with self.app.app_context():
            db.session.get(QRChallenge, config['password_qr_id']).secure_token = token
            db.session.commit()
        self.assertEqual(self.admin.post(f"/api/admin/round3/{config['id']}/activate", json={}).status_code, 200)
        return config['id']

    def round3(self):
        self.quiz()
        self.config_id = self.configure_round3()
        self.assertEqual(self.scan('round3-token').status_code,200)

    def final(self, review=True):
        self.round3()
        result=self.team.post('/api/team/round3/password',json={'password':'forty-two'})
        self.assertEqual(result.status_code,200, result.get_json())
        for action, payload in [('sheet', {'path':'PASSWORD'}), ('submit', {})]:
            result=self.admin.post(f'/api/admin/round3/{self.config_id}/{action}', json=payload)
            self.assertEqual(result.status_code,200,result.get_json())
        if review:
            result=self.admin.post(f'/api/admin/round3/{self.config_id}/review',json={'points':15,'reason':'Physical sheet evaluated'})
            self.assertEqual(result.status_code,200,result.get_json())

    def test_auth_and_invalid_credentials(self):
        client=self.app.test_client()
        self.assertEqual(client.post('/team/login',data={'team_id':'invalid','pin':'invalid'}).status_code,200)
        self.assertEqual(client.post('/admin/login',data={'username':'operator','password':'invalid'}).status_code,200)
        self.assertEqual(client.get('/api/team/dashboard').status_code,403)
        self.assertEqual(self.team.get('/api/overview').status_code,403)
        self.assertEqual(self.team.post('/api/admin/teams/1/score',json={'points':100}).status_code,403)

    def test_rolling_batches_release_on_first_round3_entry(self):
        from models import Batch
        others=[self.new_team() for _ in range(9)]
        batches=self.admin.get('/api/admin/batches').get_json()['batches']
        self.assertEqual([len(b['teams']) for b in batches],[5,5])
        self.assertEqual([b['status'] for b in batches],['RELEASED','WAITING'])
        waiting=others[4][0]
        self.assertIn('waiting for release',waiting.post('/api/team/rounds/1/start',json={}).get_json()['error'])
        self.round1(others[0][0])
        self.assertEqual(self.admin.get('/api/admin/batches').get_json()['batches'][1]['status'],'WAITING')
        self.round3()
        batches=self.admin.get('/api/admin/batches').get_json()['batches']
        self.assertEqual(batches[1]['status'],'RELEASED')
        self.assertIsNotNone(batches[0]['triggered_at'])
        self.assertEqual(waiting.post('/api/team/rounds/1/start',json={}).status_code,200)
        with self.app.app_context():
            self.assertEqual(Batch.query.count(),2)
            self.assertEqual(ActivityLog.query.filter_by(action='BATCH_RELEASED',target='2').count(),1)

    def test_open_all_rounds_keeps_waiting_batch_out_of_round_one(self):
        with self.app.app_context():
            event = db.session.get(Event, 1)
            event.active = False
            for row in Round.query:
                row.status = 'READY' if row.number == 1 else 'LOCKED'
            db.session.commit()
        waiting = [self.new_team() for _ in range(5)][-1][0]
        opened = self.admin.post('/api/rounds/start-all', json={})
        self.assertEqual(opened.status_code, 200)
        self.assertEqual([row['status'] for row in self.admin.get('/api/rounds').get_json()], ['ACTIVE'] * 3)
        self.assertEqual(self.team.post('/api/team/rounds/1/start', json={}).status_code, 200)
        blocked = waiting.post('/api/team/rounds/1/start', json={})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn('batch is waiting', blocked.get_json()['error'])

    def test_super_admin_can_delete_empty_batches_in_any_state(self):
        waiting = self.admin.post('/api/admin/batches', json={}).get_json()
        with self.app.app_context():
            team = db.session.get(Team, self.credentials['team']['id'])
            team.batch_id = waiting['id']
            team.batch_position = 1
            db.session.commit()
        blocked = self.admin.delete(f"/api/admin/batches/{waiting['id']}")
        self.assertEqual(blocked.status_code, 409)
        empty = self.admin.post('/api/admin/batches', json={}).get_json()
        with self.app.app_context():
            db.session.get(Batch, empty['id']).status = 'COMPLETED'
            db.session.commit()
        deleted = self.admin.delete(f"/api/admin/batches/{empty['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertTrue(deleted.get_json()['deleted'])
        paused = self.admin.post('/api/admin/batches', json={}).get_json()
        with self.app.app_context():
            db.session.get(Batch, paused['id']).status = 'PAUSED'
            db.session.commit()
        self.assertEqual(self.admin.delete(f"/api/admin/batches/{paused['id']}").status_code, 200)

    def test_super_admin_can_delete_unused_qr_but_preserves_assigned_qr(self):
        with self.app.app_context():
            unused = QRChallenge(qr_id='UNUSED-QR', secure_token='unused-token',
                                 round_id=1, status='INACTIVE')
            db.session.add(unused)
            db.session.flush()
            failed_scan = QRScanEvent(qr_id=unused.id, round_id=1, status='UNAUTHORIZED')
            db.session.add(failed_scan)
            db.session.commit()
            unused_id, failed_scan_id = unused.id, failed_scan.id
        deleted = self.admin.delete(f'/api/qrs/{unused_id}')
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        with self.app.app_context():
            preserved_attempt = db.session.get(QRScanEvent, failed_scan_id)
            self.assertIsNotNone(preserved_attempt)
            self.assertIsNone(preserved_attempt.qr_id)
        blocked = self.admin.delete(f'/api/qrs/{self.qr1}')
        self.assertEqual(blocked.status_code, 409)
        unchanged_identity = self.admin.patch(f'/api/qrs/{self.qr1}', json={
            'qr_id': 'QR-07', 'round_id': 1, 'question_id': None,
            'quiz_id': None, 'title': 'Assigned envelope', 'status': 'ACTIVE',
        })
        self.assertEqual(unchanged_identity.status_code, 200, unchanged_identity.get_json())

    def test_qr_edit_updates_all_configuration_fields(self):
        with self.app.app_context():
            quiz = Quiz.query.first()
            question = Question.query.filter_by(round_id=2).first()
            qr = QRChallenge(qr_id='EDIT-ME', secure_token='edit-me-token',
                             round_id=1, status='INACTIVE')
            db.session.add(qr)
            db.session.commit()
            qr_id, quiz_id, question_id = qr.id, quiz.id, question.id
        response = self.admin.patch(f'/api/qrs/{qr_id}', json={
            'qr_id': 'DESTINATION-QR',
            'round_id': 2,
            'question_id': question_id,
            'quiz_id': quiz_id,
            'title': 'Updated destination',
            'clue': 'Follow the blue sign',
            'room': 'North Hall',
            'status': 'ACTIVE',
            'expires_at': '2030-01-01T12:00:00Z',
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = response.get_json()['qr']
        self.assertEqual(saved['qr_id'], 'DESTINATION-QR')
        self.assertEqual(saved['round'], 2)
        self.assertEqual(saved['question_id'], question_id)
        self.assertEqual(saved['quiz_id'], quiz_id)
        self.assertEqual(saved['title'], 'Updated destination')
        self.assertEqual(saved['clue'], 'Follow the blue sign')
        self.assertEqual(saved['room'], 'North Hall')
        self.assertEqual(saved['status'], 'ACTIVE')
        self.assertTrue(saved['expires_at'].startswith('2030-01-01T12:00:00'))

    def test_super_admin_can_permanently_delete_team_without_history(self):
        created = self.admin.post('/api/teams', json={
            'team_name': 'Unused roster', 'member_1': 'Alex'
        }).get_json()
        team_id = created['team']['id']
        deleted = self.admin.delete(
            f'/api/teams/{team_id}?permanent=true',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        remaining_ids = [team['id'] for team in self.admin.get('/api/teams').get_json()]
        self.assertNotIn(team_id, remaining_ids)

    def test_super_admin_can_add_assistant_without_super_admin_privileges(self):
        created = self.admin.post('/api/admin/accounts', json={
            'username': 'assistant', 'password': 'assistant-password-123', 'role': 'admin'
        })
        self.assertEqual(created.status_code, 201)
        assistant = self.app.test_client()
        self.assertEqual(assistant.post('/admin/login', data={
            'username': 'assistant', 'password': 'assistant-password-123'
        }).status_code, 302)
        self.assertEqual(assistant.get('/api/admin/batches').status_code, 200)
        self.assertEqual(assistant.patch('/api/admin/event', json={'active': False}).status_code, 403)

    def test_batch_capacity_reassignment_and_manual_controls(self):
        for _ in range(5):self.new_team()
        batches=self.admin.get('/api/admin/batches').get_json()['batches']
        first,second=batches
        reversed_ids=[t['id'] for t in reversed(first['teams'])]
        reordered=self.admin.post(f"/api/admin/batches/{first['id']}/reorder",json={'team_ids':reversed_ids})
        self.assertEqual([t['id'] for t in reordered.get_json()['teams']],reversed_ids)
        moved=second['teams'][0]['id']
        self.assertEqual(self.admin.post(f"/api/admin/batches/{first['id']}/teams",json={'team_id':moved}).status_code,409)
        self.assertEqual(self.admin.post(f"/api/admin/batches/{first['id']}/teams",json={'team_id':moved,'override':True}).status_code,200)
        self.new_team()
        self.assertEqual(self.admin.post(f"/api/admin/batches/{second['id']}/pause",json={'reason':'check'}).status_code,409)
        judge=self.app.test_client();judge.post('/admin/login',data={'username':'judge','password':'a-secure-test-password'})
        self.assertEqual(judge.post(f"/api/admin/batches/{second['id']}/release",json={'reason':'early'}).status_code,403)
        self.assertEqual(self.admin.post(f"/api/admin/batches/{second['id']}/release",json={'reason':'early'}).status_code,200)
        self.assertEqual(self.admin.post('/api/admin/batches',json={}).status_code,201)
        self.round3()
        self.assertEqual(self.admin.get('/api/admin/batches').get_json()['batches'][2]['status'],'WAITING')
        with self.app.app_context():
            self.assertEqual(ActivityLog.query.filter_by(action='BATCH_RELEASED',target='2').count(),1)

    def test_empty_next_batch_releases_when_team_is_assigned(self):
        self.assertEqual(self.admin.post('/api/admin/batches',json={}).status_code,201)
        self.round3()
        self.assertEqual(self.admin.get('/api/admin/batches').get_json()['batches'][1]['status'],'WAITING')
        later,_=self.new_team()
        self.assertEqual(later.get('/api/team/dashboard').get_json()['team']['batch_status'],'RELEASED')

    def test_disabled_team_frees_capacity_and_pause_blocks_start(self):
        others=[self.new_team() for _ in range(4)]
        last_id=others[-1][1]['team']['id']
        self.assertEqual(self.admin.put(f'/api/teams/{last_id}',json={'status':'DISQUALIFIED'}).status_code,200)
        replacement,_=self.new_team()
        self.assertEqual(replacement.get('/api/team/dashboard').get_json()['team']['batch_number'],1)
        self.assertEqual(self.admin.put(f'/api/teams/{last_id}',json={'status':'READY'}).status_code,409)
        self.assertEqual(self.admin.put(f'/api/teams/{last_id}',json={'status':'READY','batch_override':True}).status_code,200)
        batch_id=self.admin.get('/api/admin/batches').get_json()['batches'][0]['id']
        self.assertEqual(self.admin.post(f'/api/admin/batches/{batch_id}/pause',json={'reason':'room check'}).status_code,200)
        self.assertIn('waiting for release',replacement.post('/api/team/rounds/1/start',json={}).get_json()['error'])
        self.assertEqual(self.admin.post(f'/api/admin/batches/{batch_id}/resume',json={'reason':'room ready'}).status_code,200)
        self.assertEqual(replacement.post('/api/team/rounds/1/start',json={}).status_code,200)

    def test_login_rate_limit_and_pin_revocation(self):
        client=self.app.test_client()
        for _ in range(10):
            self.assertEqual(client.post('/team/login',data={'team_id':'INVALID','pin':'bad'}).status_code,200)
        self.assertEqual(client.post('/team/login',data={'team_id':'INVALID','pin':'bad'}).status_code,429)
        self.admin.post(f"/api/teams/{self.credentials['team']['id']}/reset-pin",json={})
        self.assertEqual(self.team.get('/api/team/dashboard').status_code,403)

    def test_login_rate_limit_cannot_be_evaded_by_changing_identity(self):
        client = self.app.test_client()
        source = {'REMOTE_ADDR': '192.0.2.10'}
        for index in range(30):
            response = client.post('/team/login', data={'team_id': f'UNKNOWN-{index}', 'pin': 'bad'},
                                   environ_overrides=source)
            self.assertEqual(response.status_code, 200)
        response = client.post('/team/login', data={'team_id': 'ANOTHER', 'pin': 'bad'},
                               environ_overrides=source)
        self.assertEqual(response.status_code, 429)

    def test_member_count_validation_and_edit(self):
        self.assertEqual(self.admin.post('/api/teams',json={'team_name':'Empty'}).status_code,400)
        for _ in range(2):
            self.assertEqual(self.admin.put(f"/api/teams/{self.credentials['team']['id']}",json={'member_2':'Sam'}).status_code,200)
        with self.app.app_context():
            team=db.session.get(Team,self.credentials['team']['id'])
            self.assertEqual([m.name for m in team.members],['Alex','Sam'])

    def test_valid_scan_and_duplicate_audit(self):
        self.round1()
        self.assertEqual(self.scan('round1-token').status_code,409)
        with self.app.app_context():
            self.assertEqual(QRScanEvent.query.order_by(QRScanEvent.id).all()[-1].status,'ALREADY_SCANNED')
            self.assertEqual(Score.query.filter_by(round_id=1).one().points,20)
            self.assertEqual(db.session.get(Team,self.credentials['team']['id']).state,'ROUND_1_COMPLETED')

    def test_invalid_unauthorized_inactive_wrong_round_scans(self):
        self.assertEqual(self.scan('invalid').status_code,404)
        client=self.app.test_client()
        self.assertEqual(self.scan('round1-token',client).status_code,403)
        self.assertEqual(self.scan('round2-token').status_code,409)
        self.admin.post(f'/api/qrs/{self.qr1}/deactivate',json={})
        self.assertEqual(self.scan('round1-token').status_code,409)
        with self.app.app_context():
            rows=QRScanEvent.query.order_by(QRScanEvent.id).all()
            self.assertEqual([r.status for r in rows],['INVALID','UNAUTHORIZED','WRONG_ROUND','INACTIVE'])
            self.assertTrue(all(r.ip_address and r.user_agent for r in rows))

    def test_assigned_qr_and_round_bypass(self):
        with self.app.app_context():
            db.session.add(QRChallenge(qr_id='OTHER',secure_token='other',round_id=1,status='ACTIVE'));db.session.commit()
        self.team.post('/api/team/rounds/1/start',json={})
        self.assertEqual(self.scan('other').status_code,409)
        self.assertEqual(self.team.post('/api/team/rounds/1/complete',json={}).status_code,409)
        self.assertEqual(self.team.post('/api/team/rounds/3/start',json={}).status_code,409)
        self.assertEqual(self.team.get('/api/team/final').status_code,410)

    def test_pause_preserves_state_and_end_does_not_complete(self):
        self.team.post('/api/team/rounds/1/start',json={})
        self.assertEqual(self.admin.post('/api/rounds/1/pause',json={}).get_json()['status'],'PAUSED')
        self.assertEqual(self.scan('round1-token').status_code,409)
        self.assertEqual(self.admin.post('/api/rounds/1/resume',json={}).status_code,200)
        self.assertEqual(self.admin.post('/api/rounds/1/end',json={}).status_code,409)
        self.assertEqual(self.scan('round2-token').status_code,409)
        with self.app.app_context():
            self.assertEqual(RoundSession.query.one().status,'ACTIVE')

    def test_quiz_persistence_submission_scoring_and_hidden_results(self):
        self.round1();self.assertEqual(self.scan('round2-token').status_code,200)
        result=self.team.get('/api/team/quiz').get_json()
        self.assertEqual(len(result['questions']),10)
        self.assertNotIn('correct_answer',str(result))
        self.assertNotIn('points',str(result))
        self.assertEqual(self.team.post('/api/team/quiz/submit',json={}).status_code,400)
        for q in result['questions']:
            self.assertEqual(self.team.put(f"/api/team/quiz/answers/{q['id']}",json={'answer':'A'}).get_json(),{'saved':True})
        self.assertEqual(len(self.team.get('/api/team/quiz').get_json()['answers']),10)
        submitted=self.team.post('/api/team/quiz/submit',json={'score':999999})
        self.assertEqual(submitted.status_code,200)
        self.assertNotIn('score',str(submitted.get_json()))
        self.assertEqual(self.team.post('/api/team/quiz/submit',json={}).status_code,409)
        self.assertEqual(self.team.put(f"/api/team/quiz/answers/{result['questions'][0]['id']}",json={'answer':'B'}).status_code,409)
        summary=self.team.get('/api/team/dashboard').get_json()
        self.assertIsNone(summary['score']);self.assertNotIn('score',summary['team'])
        self.assertEqual(self.team.get('/api/leaderboard').get_json(),[])
        with self.app.app_context():
            self.assertEqual(QuizAttempt.query.one().score,20)
            self.assertEqual(Score.query.filter_by(round_id=2).one().points,20)

    def test_cannot_save_another_team_question_or_edit_used_bank(self):
        questions=self.quiz()
        self.assertEqual(self.admin.patch(f"/api/admin/questions/{questions[0]['id']}",json={'correct_answer':'B'}).status_code,409)
        other,_=self.new_team()
        self.assertEqual(other.put(f"/api/team/quiz/answers/{questions[0]['id']}",json={'answer':'A'}).status_code,409)
        self.assertEqual(other.get('/api/team/quiz').status_code,409)
        self.assertEqual(self.team.get('/api/admin/assignments').status_code,403)
        self.assertEqual(self.team.get('/api/admin/export/quiz-results.csv').status_code,403)

    def test_three_failed_password_attempts_persist_without_sheet_access(self):
        self.round3()
        for i in range(3):
            response=self.team.post('/api/team/round3/password',json={'password':'wrong','attempts':0})
            self.assertEqual(response.status_code,200,response.get_json())
            self.assertEqual(response.get_json()['attempts_remaining'],2-i)
            self.assertFalse(response.get_json()['password_solved'])
        self.assertEqual(self.team.post('/api/team/round3/password',json={'password':'forty-two'}).status_code,409)
        client=self.app.test_client();client.post('/team/login',data={'team_id':self.credentials['team']['team_id'],'pin':self.credentials['login_pin']})
        self.assertEqual(client.get('/api/team/round3').get_json()['attempts_remaining'],0)
        self.assertEqual(self.admin.post(f'/api/admin/round3/{self.config_id}/sheet',json={'path':'PASSWORD'}).status_code,409)
        with self.app.app_context():
            self.assertEqual(OfflineRound3.query.one().password_attempts,3)
            self.assertEqual(ActivityLog.query.filter_by(action='OFFLINE_PASSWORD_ATTEMPT').count(),3)
            self.assertEqual(FinalAssignment.query.count(),0)

    def test_successful_password_qualifies_for_organizer_sheet(self):
        self.round3()
        response=self.team.post('/api/team/round3/password',json={'password':'forty-two'})
        self.assertTrue(response.get_json()['password_solved'])
        self.assertIn('organizer', response.get_json()['message'])
        self.assertNotIn('questions',response.get_json())
        self.assertEqual(self.team.post('/api/team/round3/password',json={'password':'anything'}).status_code,409)
        self.assertEqual(self.admin.post(f'/api/admin/round3/{self.config_id}/sheet',json={'path':'PASSWORD'}).status_code,200)

    def test_round3_team_assignment_exclusivity(self):
        self.round3()
        other,_=self.new_team();self.quiz(other)
        self.assertEqual(self.scan('round3-token',other).status_code,409)
        with self.app.app_context():
            self.assertEqual(OfflineRound3.query.count(),1)
            self.assertEqual(DesktopSession.query.count(),0)
        self.assertEqual(other.get('/desktop/1').status_code,410)

    def test_paper_submission_immutable_and_scores(self):
        self.final()
        self.assertEqual(self.admin.post(f'/api/admin/round3/{self.config_id}/submit',json={}).status_code,409)
        self.assertEqual(self.team.post('/api/team/final/submit',json={}).status_code,410)
        with self.app.app_context():
            self.assertIsNotNone(OfflineRound3.query.one().reviewed_at)
            self.assertEqual(Score.query.filter_by(round_id=3).one().points,15)
            self.assertEqual(db.session.get(Team,self.credentials['team']['id']).state,'COMPLETED')

    def test_result_lock_publication_and_unlock_reason(self):
        self.final()
        self.assertEqual(self.admin.post('/api/results/publish',json={}).status_code,409)
        for n in (1,2,3):self.admin.post(f'/api/rounds/{n}/end',json={})
        generated=self.admin.post('/api/results/generate',json={})
        self.assertEqual(generated.status_code,201,generated.get_json())
        self.assertEqual(self.admin.post('/api/results/lock',json={}).status_code,200)
        self.assertEqual(self.admin.post(f"/api/admin/teams/{self.credentials['team']['id']}/score",json={'bonus':10,'reason':'bonus'}).status_code,409)
        self.assertEqual(self.admin.post('/api/results/publish',json={}).status_code,200)
        self.assertEqual(self.team.get('/api/team/dashboard').get_json()['score'],55)
        self.assertEqual(self.team.get('/api/leaderboard').get_json(),[])
        self.assertEqual(self.admin.post('/api/results/unlock',json={}).status_code,400)
        self.assertEqual(self.admin.post('/api/results/unlock',json={'reason':'judging correction'}).status_code,200)
        self.assertIsNone(self.team.get('/api/team/dashboard').get_json()['score'])

    def test_roles_exports_qr_archive_and_reset_guard(self):
        judge=self.app.test_client();judge.post('/admin/login',data={'username':'judge','password':'a-secure-test-password'})
        self.assertEqual(judge.patch('/api/admin/event',json={'active':False}).status_code,403)
        self.assertEqual(judge.post('/api/admin/test-reset',json={}).status_code,403)
        for kind in ('teams','scans','quiz-responses','quiz-results','round3-sheets','scores','leaderboard','logs'):
            self.assertEqual(self.admin.get(f'/api/admin/export/{kind}.csv').status_code,200)
        self.assertEqual(self.admin.get('/api/qrs/download').status_code,200)
        self.assertEqual(self.admin.get('/admin/qrs/print').status_code,200)
        self.assertEqual(self.admin.get('/station/1').status_code,410)
        self.assertEqual(self.admin.post('/api/admin/test-reset',json={'confirmation':'RESET TEST PROGRESS'}).status_code,409)
        self.app.config['EVENT_MODE']='PRODUCTION'
        self.assertEqual(self.admin.post('/api/admin/test-reset',json={'confirmation':'RESET TEST PROGRESS'}).status_code,403)
        self.assertEqual(self.admin.post(f'/api/qrs/{self.qr1}/archive',json={}).status_code,200)
        self.assertEqual(self.scan('round1-token').get_json()['status'],'INACTIVE')

    def test_team_socket_never_receives_hidden_scores(self):
        participant=socketio.test_client(self.app,flask_test_client=self.team)
        participant.emit('join_admin');participant.emit('join_participant');participant.get_received()
        with self.app.app_context():emit_leaderboard()
        self.assertEqual(participant.get_received(),[])
        participant.disconnect()

    def test_manual_sheet_review_and_lock_staleness(self):
        self.final(review=False)
        for n in (1,2,3):self.admin.post(f'/api/rounds/{n}/end',json={})
        self.assertEqual(self.admin.post('/api/results/generate',json={}).status_code,409)
        review=self.admin.post(f'/api/admin/round3/{self.config_id}/review',json={'points':9,'reason':'Paper judged'})
        self.assertEqual(review.status_code,200)
        self.assertEqual(self.admin.post('/api/results/generate',json={}).status_code,201)
        self.admin.post(f"/api/admin/teams/{self.credentials['team']['id']}/score",json={'bonus':5,'reason':'judge adjustment'})
        self.assertEqual(self.admin.post('/api/results/lock',json={}).status_code,409)

    def test_reset_removes_only_test_progress(self):
        self.final()
        self.assertEqual(self.admin.patch('/api/admin/event',json={'active':False}).status_code,200)
        self.assertEqual(self.admin.post('/api/admin/test-reset',json={'confirmation':'RESET TEST PROGRESS'}).status_code,200)
        with self.app.app_context():
            self.assertEqual(Team.query.count(),0)
            self.assertEqual(PasswordAttempt.query.count(),0)
            self.assertEqual(Question.query.count(),22)
            self.assertEqual(OfflineRound3.query.count(),0)
            self.assertEqual(Admin.query.count(),2)
            self.assertEqual(ActivityLog.query.one().action,'TEST_RESET')

    def test_admin_account_disable_revokes_session_and_socket(self):
        judge=self.app.test_client()
        judge.post('/admin/login',data={'username':'judge','password':'a-secure-test-password'})
        connected=socketio.test_client(self.app,flask_test_client=judge)
        connected.emit('join_admin')
        with self.app.app_context():pk=Admin.query.filter_by(username='judge').one().id
        self.assertEqual(self.admin.patch(f'/api/admin/accounts/{pk}',json={'active':False}).status_code,200)
        self.assertEqual(judge.get('/api/overview').status_code,403)
        self.assertFalse(connected.is_connected())

    def test_canonical_qr_url_and_input_errors(self):
        from utils.qr_generator import scan_url
        with self.app.test_request_context('/'):
            self.app.config['PUBLIC_BASE_URL']='https://quest.college.example'
            self.assertEqual(scan_url('opaque-token'),'https://quest.college.example/scan/opaque-token')
        self.assertEqual(self.admin.post('/api/qrs',json={'round_id':'bad'}).status_code,400)
        self.assertEqual(self.admin.post('/api/qrs',json=[]).status_code,400)
        self.assertEqual(self.admin.post('/api/admin/quizzes',json={'title':'Bad','question_ids':[{}]*10}).status_code,400)

    def test_production_rejects_insecure_configuration(self):
        import os
        from unittest.mock import patch
        from config import Config
        environment={'APP_ENV':'production','EVENT_MODE':'PRODUCTION',
                     'SECRET_KEY':'test-only-random-shaped-secret-at-least-32-characters',
                     'COOKIE_SECURE':'true','PUBLIC_BASE_URL':'https://quest.college.example',
                     'DATABASE_URL':'postgresql://localhost/test'}
        with patch.dict(os.environ,environment):
            Config.validate_runtime()
            for key,value in [('SECRET_KEY','replace-with-a-random-secret-at-least-32-characters'),
                              ('COOKIE_SECURE','false'),('DATABASE_URL','sqlite:///test.db'),
                              ('EVENT_MODE','TEST'),('PUBLIC_BASE_URL','http://quest.college.example')]:
                with patch.dict(os.environ,{key:value}):
                    with self.assertRaises(RuntimeError):Config.validate_runtime()

    def test_production_restricts_host_to_public_url(self):
        production = create_app({"TESTING": True, "APP_ENV": "production",
                                 "PUBLIC_BASE_URL": "https://quest.college.example",
                                 "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
        client = production.test_client()
        self.assertEqual(client.get('/admin/login', base_url='https://quest.college.example').status_code, 200)
        self.assertEqual(client.get('/admin/login', base_url='https://other.example').status_code, 400)

    def test_csrf_is_enforced(self):
        self.app.config['WTF_CSRF_ENABLED']=True
        response=self.team.post('/api/team/scan',json={'token':'round1-token'})
        self.assertEqual(response.status_code,400)
        self.assertIn('CSRF',response.get_json()['error'])

    def test_hidden_sheet_path_is_rejected(self):
        self.round3()
        response=self.admin.post(f'/api/admin/round3/{self.config_id}/sheet',json={'path':'LOCATION'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.scan('round3-token-location').status_code,404)
        state=self.team.get('/api/team/round3').get_json()
        self.assertNotIn('location_clue',state)
        with self.app.app_context():
            self.assertEqual(QRChallenge.query.filter_by(round_id=3).count(),1)

    def test_round3_scan_releases_only_one_batch_and_preserves_riddle(self):
        for _ in range(5):self.new_team()
        self.round3()
        self.assertEqual(self.scan('round3-token').status_code,409)
        state=self.team.get('/api/team/round3').get_json()
        self.assertTrue(state['password_clue'])
        self.assertNotIn('password_hash',state)
        self.assertEqual(state['attempts_remaining'],3)
        with self.app.app_context():
            self.assertEqual(ActivityLog.query.filter_by(action='BATCH_RELEASED',target='2').count(),1)
            self.assertEqual(RoundSession.query.filter_by(round_id=3).count(),1)

    def test_round3_configuration_and_qr_assignment_are_frozen_after_entry(self):
        self.round3()
        row=self.admin.get('/api/admin/round3').get_json()[0]
        for qr_id in (row['password_qr_id'],):
            self.assertEqual(self.admin.delete(f'/api/qrs/{qr_id}').status_code,409)
            self.assertEqual(self.admin.patch(f'/api/qrs/{qr_id}',json={'round_id':1}).status_code,409)
            self.assertEqual(self.admin.post(f'/api/qrs/{qr_id}/regenerate',json={}).status_code,409)
        self.assertEqual(self.admin.patch(f'/api/admin/round3/{self.config_id}',json={'password':'new'}).status_code,409)
        self.assertEqual(self.admin.patch(f"/api/qrs/{row['password_qr_id']}",json={'clue':'Changed'}).status_code,409)

    def test_round3_validation_and_admin_boundaries(self):
        self.assertEqual(self.team.post('/api/admin/round3',json={}).status_code,403)
        self.assertEqual(self.admin.post('/api/admin/round3',json={'team_id':self.credentials['team']['id'],'password':'secret'}).status_code,400)
        self.assertEqual(self.team.get('/api/team/round3').get_json(),{'configured':False})
        config_id=self.configure_round3()
        self.assertEqual(self.scan('round3-token').status_code,409)
        self.assertEqual(self.team.post(f'/api/admin/round3/{config_id}/sheet',json={'path':'PASSWORD'}).status_code,403)
        self.assertEqual(self.admin.post(f'/api/admin/round3/{config_id}/submit',json={}).status_code,409)
        self.assertEqual(self.admin.post(f'/api/admin/round3/{config_id}/review',json={'points':10,'reason':'Premature'}).status_code,409)
        self.assertEqual(self.admin.post('/api/admin/round3',json={'team_id':self.credentials['team']['id']}).status_code,409)
        state=self.team.get('/api/team/dashboard').get_json()['round3']
        self.assertIsNone(state['password_clue']);self.assertNotIn('location_clue',state)

    def test_password_works_without_online_bank_and_respects_pause(self):
        self.round3()
        with self.app.app_context():
            Question.query.filter_by(round_id=3).delete();db.session.commit()
        self.admin.post('/api/rounds/3/pause',json={})
        self.assertEqual(self.team.post('/api/team/round3/password',json={'password':'forty-two'}).status_code,409)
        self.assertEqual(self.team.get('/api/team/round3').get_json()['attempts_remaining'],3)
        self.admin.post('/api/rounds/3/resume',json={})
        self.assertTrue(self.team.post('/api/team/round3/password',json={'password':'forty-two'}).get_json()['password_solved'])
        with self.app.app_context():self.assertEqual(FinalAssignment.query.count(),0)

    def test_human_marks_require_returned_sheet_and_respect_limits_and_locks(self):
        self.final(review=False)
        review=f'/api/admin/round3/{self.config_id}/review'
        for payload in ({'points':101,'reason':'Too high'},{'points':-1,'reason':'Negative'},{'points':10}):
            self.assertEqual(self.admin.post(review,json=payload).status_code,400)
        self.assertEqual(self.admin.post(f"/api/admin/teams/{self.credentials['team']['id']}/score",json={'round_id':3,'points':10,'reason':'Bypass'}).status_code,409)
        self.assertEqual(self.admin.post(review,json={'points':10,'reason':'Judged'}).status_code,200)
        self.assertEqual(self.admin.post(review,json={'points':12,'reason':'Rechecked'}).status_code,200)
        with self.app.app_context():
            self.assertEqual(Score.query.filter_by(round_id=3).one().points,12)
            db.session.get(Event,1).results_locked=True;db.session.commit()
        self.assertEqual(self.admin.post(review,json={'points':15,'reason':'Locked'}).status_code,409)


    def test_team_completion_stops_time_and_admin_receipt_preserves_it(self):
        self.round3()
        self.assertEqual(self.team.post('/api/team/round3/complete',json={}).status_code,409)
        self.team.post('/api/team/round3/password',json={'password':'forty-two'})
        with self.app.app_context():
            sessions=RoundSession.query.filter_by(team_id=self.credentials['team']['id']).order_by(RoundSession.round_id).all()
            now=utcnow()
            for session,seconds in zip(sessions,[20,30,60]):
                session.started_at=now-timedelta(seconds=seconds)
                if session.status=='COMPLETED':session.ended_at=now
            db.session.commit()
        result=self.team.post('/api/team/round3/complete',json={'elapsed_seconds':0})
        self.assertEqual(result.status_code,200,result.get_json())
        summary=self.team.get('/api/team/dashboard').get_json()
        self.assertEqual(summary['team']['state'],'COMPLETED')
        self.assertFalse(summary['session_active'])
        self.assertGreaterEqual(summary['elapsed_seconds'],110)
        finished=summary['round3']['completed_at']
        self.assertIsNotNone(finished)
        self.assertIsNone(summary['round3']['submitted_at'])
        self.assertEqual(self.team.post('/api/team/round3/complete',json={}).status_code,409)
        self.assertEqual(self.admin.post(f'/api/admin/round3/{self.config_id}/sheet',json={}).status_code,200)
        self.assertEqual(self.admin.post(f'/api/admin/round3/{self.config_id}/submit',json={}).status_code,200)
        after=self.team.get('/api/team/dashboard').get_json()
        self.assertEqual(after['round3']['completed_at'],finished)
        self.assertEqual(after['elapsed_seconds'],summary['elapsed_seconds'])
        self.assertEqual(self.admin.post(f'/api/admin/round3/{self.config_id}/review',json={'points':50,'reason':'Paper judged'}).status_code,200)
        self.assertEqual(self.team.get('/api/team/dashboard').get_json()['elapsed_seconds'],summary['elapsed_seconds'])

    def test_team_completion_requires_active_round_and_authorized_team(self):
        self.assertEqual(self.app.test_client().post('/api/team/round3/complete',json={}).status_code,403)
        self.assertEqual(self.team.post('/api/team/round3/complete',json={}).status_code,409)
        self.round3()
        self.team.post('/api/team/round3/password',json={'password':'forty-two'})
        self.admin.post('/api/rounds/3/pause',json={})
        self.assertEqual(self.team.post('/api/team/round3/complete',json={}).status_code,409)
        self.admin.post('/api/rounds/3/resume',json={})
        self.assertEqual(self.team.post('/api/team/round3/complete',json={}).status_code,200)


if __name__=='__main__':unittest.main()
