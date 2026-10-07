import unittest
from datetime import timedelta

from app import create_app
from extensions import db
from models import (Event, Answer, Admin, FinalResult, QRChallenge, QRScanEvent,
                    Round, RoundSession, Score, Team, TeamMember, utcnow)
from utils.scoring import leaderboard_rows


class EventAppTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "APP_ENV": "development",
            "EVENT_MODE": "TEST",
            "AUTO_INIT_DB": False,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-secret-key-long-enough-for-session-signing",
        })
        with self.app.app_context():
            db.create_all()
            db.session.add(Event(id=1, active=False))
            db.session.add_all([
                Round(number=1, name="QR Riddle", status="READY"),
                Round(number=2, name="Quiz Challenge", status="LOCKED"),
                Round(number=3, name="Pen & Paper Final Challenge", status="LOCKED"),
            ])
            admin = Admin(username="operator", role="super-admin")
            admin.set_password("a-secure-test-password")
            db.session.add(admin)
            db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all();db.engine.dispose()

    def login_admin(self):
        return self.client.post("/admin/login", data={
            "username": "operator", "password": "a-secure-test-password"
        })

    def test_round_specific_qr_creation_and_question_sets(self):
        self.login_admin()
        from models import Question
        with self.app.app_context():
            db.session.add_all([Question(round_id=2, prompt=f"Question {index}", correct_answer="A",
                                         option_a="A", option_b="B", option_c="C", option_d="D")
                                for index in range(10)])
            db.session.commit()
            ids = [q.id for q in Question.query.filter_by(round_id=2).order_by(Question.id)]
        created_set = self.client.post('/api/admin/quizzes', json={'title': 'AI Set', 'question_ids': ids})
        self.assertEqual(created_set.status_code, 201, created_set.get_json())
        quiz_id = created_set.get_json()['id']
        self.assertEqual(self.client.patch(f'/api/admin/quizzes/{quiz_id}', json={'title': 'AI Set 01'}).status_code, 200)
        expiry = (utcnow() + timedelta(days=1)).isoformat()
        batch = self.client.post('/api/qrs', json={'round_id': 1, 'count': 3,
                                                   'title': 'Hidden message', 'clue': 'Look near books',
                                                   'expires_at': expiry})
        self.assertEqual(batch.status_code, 201, batch.get_json())
        self.assertEqual(len(batch.get_json()['qrs']), 3)
        self.assertEqual(len({q['qr_id'] for q in batch.get_json()['qrs']}), 3)
        round_two = self.client.post('/api/qrs', json={'round_id': 2, 'title': 'AI Challenge',
                                                       'clue': 'Answer the questions', 'quiz_id': quiz_id,
                                                       'expires_at': expiry})
        self.assertEqual(round_two.status_code, 201, round_two.get_json())
        self.assertEqual(round_two.get_json()['qr']['quiz_id'], quiz_id)
        round_three = self.client.post('/api/qrs', json={'round_id': 3, 'title': 'Final Challenge',
                                                         'clue': 'Find the password', 'expires_at': expiry})
        self.assertEqual(round_three.status_code, 201, round_three.get_json())
        self.assertIsNone(round_three.get_json()['qr']['quiz_id'])
        desktop = self.client.post('/api/admin/desktops', json={'name': 'Station A',
                                                                 'password': 'desktop-password',
                                                                 'clue': 'Unlock the final challenge',
                                                                 'qr_id': round_three.get_json()['qr']['id']})
        self.assertEqual(desktop.status_code, 201, desktop.get_json())
        self.assertEqual(desktop.get_json()['qr_id'], round_three.get_json()['qr']['id'])
        self.assertEqual(self.client.delete(f'/api/admin/quizzes/{quiz_id}').status_code, 409)
        self.assertEqual(self.client.post('/api/qrs', json={'round_id': 2, 'title': 'Missing set'}).status_code, 400)

    def create_team(self):
        response = self.client.post("/api/teams", json={"team_name": "Test Team", "member_1": "Alex"})
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def test_protected_admin_and_team_boundary(self):
        self.assertEqual(self.client.get("/api/overview").status_code, 403)
        self.login_admin()
        created = self.create_team()
        team_client = self.app.test_client()
        team_client.post("/team/login", data={
            "team_id": created["team"]["team_id"], "pin": created["login_pin"]
        })
        self.assertEqual(self.client.get("/api/admin/profile").status_code, 200)
        self.assertEqual(team_client.get("/api/overview").status_code, 403)
        self.assertEqual(team_client.get("/api/team/dashboard").status_code, 200)

    def test_database_health_and_team_member_records(self):
        self.login_admin()
        response = self.client.get("/health/db")
        self.assertEqual(response.get_json(), {"database": "sqlite", "status": "ok"})
        created = self.client.post("/api/teams", json={
            "team_name": "Members Team", "member_1": "Alex", "member_2": "Sam"
        })
        self.assertEqual(created.status_code, 201)
        with self.app.app_context():
            team = Team.query.filter_by(team_name="Members Team").one()
            self.assertEqual([member.name for member in team.members], ["Alex", "Sam"])
            self.assertEqual(TeamMember.query.filter_by(team_id=team.id).count(), 2)

    def test_final_result_tiebreaks_by_duration_then_completion(self):
        with self.app.app_context():
            started_at = utcnow()
            teams = []
            for team_id, name in (
                ("AIQ-001", "Slow"),
                ("AIQ-002", "Fast, later"),
                ("AIQ-003", "Fast, earlier"),
            ):
                team = Team(team_id=team_id, team_name=name, status="COMPLETED")
                team.set_pin("123456")
                db.session.add(team)
                teams.append(team)
            db.session.flush()
            for event_round in Round.query.order_by(Round.number):
                event_round.status = "ENDED"
            durations = [(120, 120), (60, 120), (60, 90)]
            for team, (duration, completion) in zip(teams, durations):
                db.session.add(Score(team_id=team.id, round_id=1, points=50))
                db.session.add(Score(team_id=team.id, round_id=3, points=10))
                for round_number in (1, 2, 3):
                    round_duration = duration if round_number == 1 else 10
                    db.session.add(RoundSession(
                        team_id=team.id,
                        round_id=round_number,
                        status="COMPLETED",
                        started_at=started_at + timedelta(seconds=completion - round_duration),
                        ended_at=started_at + timedelta(seconds=completion),
                    ))
            db.session.commit()

        self.login_admin()
        generated = self.client.post("/api/results/generate", json={})
        self.assertEqual(generated.status_code, 201, generated.get_data(as_text=True))
        results = self.client.get("/api/results").get_json()
        self.assertEqual([row["team_id"] for row in results], ["AIQ-003", "AIQ-002", "AIQ-001"])
        self.assertEqual(self.client.post("/api/results/lock", json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/results/generate", json={}).status_code, 409)
        with self.app.app_context():
            self.assertEqual(FinalResult.query.filter_by(locked=True).count(), 3)

    def test_leaderboard_tiebreak_uses_completion_time(self):
        with self.app.app_context():
            base = utcnow()
            team_1 = Team(team_id="AIQ-010", team_name="Later Finish", status="ACTIVE")
            team_1.set_pin("123456")
            team_2 = Team(team_id="AIQ-011", team_name="Earlier Finish", status="ACTIVE")
            team_2.set_pin("123456")
            db.session.add_all([team_1, team_2])
            db.session.flush()
            db.session.add_all([
                Score(team_id=team_1.id, round_id=1, points=50),
                Score(team_id=team_1.id, round_id=2, points=30),
                Score(team_id=team_2.id, round_id=1, points=50),
                Score(team_id=team_2.id, round_id=2, points=30),
                RoundSession(team_id=team_1.id, round_id=1, status="COMPLETED", started_at=base, ended_at=base + timedelta(seconds=120)),
                RoundSession(team_id=team_1.id, round_id=2, status="COMPLETED", started_at=base + timedelta(seconds=200), ended_at=base + timedelta(seconds=380)),
                RoundSession(team_id=team_2.id, round_id=1, status="COMPLETED", started_at=base + timedelta(seconds=10), ended_at=base + timedelta(seconds=130)),
                RoundSession(team_id=team_2.id, round_id=2, status="COMPLETED", started_at=base + timedelta(seconds=170), ended_at=base + timedelta(seconds=350)),
            ])
            db.session.commit()
        with self.app.app_context():
            rows = leaderboard_rows()
        self.assertEqual([row["team_id"] for row in rows], ["AIQ-011", "AIQ-010"])
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[1]["rank"], 2)
        self.assertEqual(rows[0]["time"], 300)

    def test_team_cannot_skip_a_round(self):
        self.login_admin()
        created = self.create_team()
        with self.app.app_context():
            Round.query.filter_by(number=2).first().status = "ACTIVE"
            db.session.commit()
        team_client = self.app.test_client()
        team_client.post("/team/login", data={
            "team_id": created["team"]["team_id"], "pin": created["login_pin"]
        })
        self.assertEqual(team_client.post("/api/team/rounds/2/start", json={}).status_code, 409)

    def test_rounds_open_together_and_do_not_unlock_in_sequence(self):
        self.login_admin()
        opened = self.client.post("/api/rounds/start-all", json={})
        self.assertEqual(opened.status_code, 200)
        self.assertEqual([row["status"] for row in opened.get_json()["rounds"]], ["ACTIVE"] * 3)
        self.assertEqual(self.client.post("/api/rounds/start-all", json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/rounds/1/end", json={}).status_code, 200)
        with self.app.app_context():
            self.assertEqual(Round.query.filter_by(number=2).one().status, "ACTIVE")
            Round.query.filter_by(number=2).one().status = "ENDED"
            Round.query.filter_by(number=3).one().status = "READY"
            db.session.add(QRScanEvent(status="UNAUTHORIZED"))
            db.session.commit()
        reopened = self.client.post("/api/rounds/start-all", json={})
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual([row["status"] for row in reopened.get_json()["rounds"]], ["ACTIVE"] * 3)
        with self.app.app_context():
            self.assertIsNone(Round.query.filter_by(number=1).one().ended_at)

    def test_ended_rounds_with_progress_cannot_be_reopened(self):
        self.login_admin()
        with self.app.app_context():
            db.session.get(Round, 1).status = "ENDED"
            team = Team(team_id="AIQ-100", team_name="Recorded Team")
            team.set_pin("123456")
            db.session.add(team)
            db.session.flush()
            db.session.add(Score(team_id=team.id, round_id=1, points=10))
            db.session.commit()
        response = self.client.post("/api/rounds/start-all", json={})
        self.assertEqual(response.status_code, 409)
        with self.app.app_context():
            self.assertEqual(db.session.get(Round, 1).status, "ENDED")

    def test_ended_rounds_cannot_reopen_in_production_mode(self):
        self.login_admin()
        with self.app.app_context():
            db.session.get(Round, 1).status = "ENDED"
            db.session.get(Event, 1).mode = "PRODUCTION"
            db.session.commit()
        self.assertEqual(self.client.post("/api/rounds/start-all", json={}).status_code, 409)

    def test_only_super_admin_can_reopen_test_rounds(self):
        with self.app.app_context():
            db.session.get(Round, 1).status = "ENDED"
            assistant = Admin(username="assistant", role="admin")
            assistant.set_password("a-secure-test-password")
            db.session.add(assistant)
            db.session.commit()
        self.client.post("/admin/login", data={
            "username": "assistant", "password": "a-secure-test-password"
        })
        self.assertEqual(self.client.post("/api/rounds/start-all", json={}).status_code, 403)

    def test_legacy_round_start_opens_every_round(self):
        self.login_admin()
        self.assertEqual(self.client.post("/api/rounds/1/start", json={}).status_code, 200)
        self.assertEqual([row["status"] for row in self.client.get("/api/rounds").get_json()], ["ACTIVE"] * 3)
        self.assertEqual(self.client.post("/api/rounds/2/unlock", json={}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
