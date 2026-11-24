import importlib, os
from fastapi.testclient import TestClient

os.environ['DATABASE_URL'] = 'sqlite:////tmp/lyftr-test.db'
os.environ['LLM_API_KEYS'] = 'fake1,fake2'
os.environ['ENABLE_FAILURE_SIMULATION'] = 'true'
import app.main as main
importlib.reload(main)
client = TestClient(main.app)

def setup_module():
    try: os.remove('/tmp/lyftr-test.db')
    except FileNotFoundError: pass
    main.init_db()

def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['keys_configured'] == 2

def test_validation():
    assert client.post('/chat', json={'session_id':'x','message':'   '}).status_code == 422

def test_unknown_session():
    assert client.get('/sessions/does-not-exist/messages').status_code == 404

def test_all_simulated_failures_do_not_write_history():
    r = client.post('/chat', headers={'X-Simulate-Failure':'*=429'}, json={'session_id':'fail-test','message':'hello'})
    assert r.status_code == 503
    assert r.json() == {'detail':'all providers unavailable'}
    assert client.get('/sessions/fail-test/messages').status_code == 404
