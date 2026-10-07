"""Complete event simulation in a NEW temporary database/schema; never reset input DBs."""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from app import create_app
from extensions import db
from flask_migrate import upgrade
from models import Batch, Desktop, Event, FinalAssignment, PasswordAttempt, QRChallenge, Score, Team, utcnow
from test_event_flow import seed_content


def simulate(count, database_url=None):
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='aiquest-simulation-') as directory:
        schema=None
        if database_url:
            import psycopg
            from psycopg import sql
            schema='aiquest_sim_'+uuid.uuid4().hex
            with psycopg.connect(database_url.replace('postgresql+psycopg://','postgresql://')) as connection:
                connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            uri=database_url.replace('postgresql://','postgresql+psycopg://')
            options={'connect_args':{'options':f'-csearch_path={schema}'}}
        else:
            uri='sqlite:///'+str(Path(directory)/'event-test.db')
            options={}
        app=create_app({'TESTING':True,'AUTO_INIT_DB':False,'WTF_CSRF_ENABLED':False,
                        'SQLALCHEMY_DATABASE_URI':uri,'SQLALCHEMY_ENGINE_OPTIONS':options,
                        'SECRET_KEY':uuid.uuid4().hex,'EVENT_MODE':'TEST'})
        import logging
        app.logger.setLevel(logging.WARNING)
        try:
            with app.app_context():
                upgrade(directory=str(Path(__file__).resolve().parents[1]/'migrations'))
                qr1=seed_content()
                pin_hash=None
                password_hash=Desktop.query.first().password_hash
                for i in range(count):
                    if i % 5 == 0:
                        batch=Batch(number=i//5+1,capacity=5,status='RELEASED' if i==0 else 'WAITING',
                                    released_at=utcnow() if i==0 else None)
                        db.session.add(batch)
                        db.session.flush()
                    team=Team(team_id=f'AQ-{i:03d}',team_name=f'Simulation {i}',member_1='Test member',assigned_qr_id=qr1,
                              batch_id=batch.id,batch_position=i%5+1)
                    if pin_hash is None:team.set_pin('123456');pin_hash=team.pin_hash
                    else:team.pin_hash=pin_hash
                    qr=QRChallenge(qr_id=f'SIM-DESKTOP-{i}',secure_token=f'sim-desktop-{i}',round_id=3,clue='Test clue',status='ACTIVE')
                    db.session.add_all([team,qr]);db.session.flush()
                    db.session.add(Desktop(name=f'SIM-DESKTOP-{i}',qr_id=qr.id,password_hash=password_hash))
                db.session.commit()
            timings=[]
            wave_count=(count+4)//5
            wave_triggers=[threading.Event() for _ in range(wave_count)]
            def run_team(i):
                client=app.test_client()
                def call(method,path,payload=None,expected=200):
                    before=time.monotonic()
                    response=getattr(client,method)(path,json=payload) if payload is not None else getattr(client,method)(path)
                    timings.append(time.monotonic()-before)
                    if response.status_code!=expected:raise AssertionError((i,path,response.status_code,response.get_json()))
                    return response.get_json()
                result=client.post('/team/login',data={'team_id':f'AQ-{i:03d}','pin':'123456'})
                assert result.status_code==302
                call('post','/api/team/rounds/1/start',{})
                call('post','/api/team/scan',{'token':'round1-token'})
                call('post','/api/team/scan',{'token':'round1-token'},409)
                call('post','/api/team/scan',{'token':'round2-token'})
                questions=call('get','/api/team/quiz')['questions']
                for q in questions:call('put',f"/api/team/quiz/answers/{q['id']}",{'answer':'A'})
                call('post','/api/team/quiz/submit',{})
                call('post','/api/team/quiz/submit',{},409)
                call('post','/api/team/scan',{'token':f'sim-desktop-{i}'})
                wave_triggers[i//5].set()
                if i%2:
                    for _ in range(3):call('post','/api/team/desktop/password',{'password':'wrong'})
                else:call('post','/api/team/desktop/password',{'password':'forty-two'})
                first=call('get','/api/team/final')
                assert first['questions']==call('get','/api/team/final')['questions']
                for q in first['questions']:call('put',f"/api/team/final/answers/{q['id']}",{'answer':'42'})
                call('post','/api/team/final/submit',{})
                call('post','/api/team/final/submit',{},409)
                assert call('get','/api/team/dashboard')['score'] is None
                assert call('get','/api/leaderboard')==[]
            with ThreadPoolExecutor(max_workers=min(count,20)) as pool:
                futures=[]
                for wave in range(wave_count):
                    if wave:
                        assert wave_triggers[wave-1].wait(120), f'Batch {wave} never reached Round 3'
                    futures.extend(pool.submit(run_team,i) for i in range(wave*5,min((wave+1)*5,count)))
                for future in futures:future.result()
            with app.app_context():
                assert all(batch.status=='COMPLETED' for batch in Batch.query)
                assert Team.query.filter_by(status='COMPLETED').count()==count
                assert PasswordAttempt.query.count()==count//2*3+(count-count//2)
                assert Score.query.count()==count*3
                assert all(s.points==20 for s in Score.query.filter_by(round_id=2))
                assignments=FinalAssignment.query.all()
                sequences={tuple(q['id'] for q in a.questions) for a in assignments}
                assert len(sequences)>1
            admin=app.test_client();admin.post('/admin/login',data={'username':'operator','password':'a-secure-test-password'})
            for n in (1,2,3):assert admin.post(f'/api/rounds/{n}/end',json={}).status_code==200
            assert admin.post('/api/results/generate',json={}).status_code==201
            assert admin.post('/api/results/lock',json={}).status_code==200
            assert admin.post('/api/results/publish',json={}).status_code==200
            ordered=sorted(timings)
            return {'teams':count,'workers':min(count,20),'database':'postgresql' if database_url else 'sqlite',
                    'requests':len(timings),'seconds':round(time.monotonic()-started,2),
                    'p95_ms':round(ordered[int(len(ordered)*.95)]*1000,2),
                    'distinct_final_sequences':len(sequences),'status':'PASS'}
        finally:
            with app.app_context():db.session.remove();db.engine.dispose()
            if schema:
                with psycopg.connect(database_url.replace('postgresql+psycopg://','postgresql://')) as connection:
                    # Only the generated simulation schema is removed.
                    connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--teams',nargs='+',type=int,default=[10,25,50,100])
    parser.add_argument('--output',default=None)
    args=parser.parse_args()
    if any(n<2 or n>1000 for n in args.teams):parser.error('Use 2–1000 teams.')
    results=[]
    for count in args.teams:
        result=simulate(count,os.getenv('SIMULATION_DATABASE_URL'));results.append(result);print(json.dumps(result),flush=True)
    if args.output:Path(args.output).write_text(json.dumps(results,indent=2)+'\n')
