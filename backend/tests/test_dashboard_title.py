from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.models import Setting, Site
from app.sites import registry
from test_v070_sites_api import _h


def test_title_persists_globally_and_can_be_cleared():
    with TestClient(app) as c:
        headers = _h(c)
        with database.session() as db:
            db.add(Site(slug='title-test', name='Branch', enabled=0, created=1))
            db.commit()
            registry.load(db)
        try:
            result = c.put('/api/settings', headers=headers, json={'dashboard_title': '  公司网络  '})
            assert result.status_code == 200
            assert result.json()['dashboard_title'] == '公司网络'
            for path in ('/api/settings?site=title-test', '/api/system', '/api/system?site=title-test'):
                assert c.get(path, headers=headers).json()['dashboard_title'] == '公司网络'
            with database.session() as db:
                assert db.get(Setting, 'dashboard_title').value == '公司网络'
            assert c.put('/api/settings', headers=headers, json={'dashboard_title': 'x' * 65}).status_code == 422
            assert c.get('/api/settings', headers=headers).json()['dashboard_title'] == '公司网络'
            assert c.put('/api/settings', headers=headers, json={'dashboard_title': ' '}).json()['dashboard_title'] == ''
        finally:
            with database.session() as db:
                row = db.get(Setting, 'dashboard_title')
                if row:
                    db.delete(row)
                db.delete(db.get(Site, 'title-test'))
                db.commit()
                registry.load(db)


def test_viewer_can_read_title_but_cannot_change_it():
    with TestClient(app) as c:
        headers = _h(c)
        created = c.post('/api/auth/users', headers=headers, json={'username': 'title-viewer', 'password': 'viewer1', 'role': 'user'})
        assert created.is_success
        try:
            token = c.post('/api/auth/login', json={'username': 'title-viewer', 'password': 'viewer1'}).json()['token']
            viewer = {'Authorization': f'Bearer {token}'}
            assert 'dashboard_title' in c.get('/api/system', headers=viewer).json()
            assert c.put('/api/settings', headers=viewer, json={'dashboard_title': 'changed'}).status_code == 403
        finally:
            c.delete(f"/api/auth/users/{created.json()['id']}", headers=headers)
