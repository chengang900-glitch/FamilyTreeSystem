"""Cookie scoping regression for root and reverse-proxied subpath deployments."""
import os
from _testenv import bootstrap, cleanup

bootstrap('subpath')
try:
    from server.app import app
    from server.service import auth
    with app.app_context():
        for base, expected in [('', '/'), ('/familytree', '/familytree/'), ('/familytree/', '/familytree/')]:
            os.environ['FTS_BASE_PATH'] = base
            response = app.response_class()
            auth.set_auth_cookies(response, 'test-access', 'test-refresh')
            cookies = response.headers.getlist('Set-Cookie')
            assert f'Path={expected};' in cookies[0], cookies[0]
            assert f'Path={expected}api/auth;' in cookies[1], cookies[1]
            assert all('HttpOnly' in c and 'SameSite=Strict' in c for c in cookies)
            cleared = auth.clear_auth_cookies(app.response_class()).headers.getlist('Set-Cookie')
            assert f'Path={expected}' in cleared[0]
            assert f'Path={expected}api/auth' in cleared[1]
    print('PASS: root/subpath/trailing-slash cookie creation and deletion')
finally:
    os.environ.pop('FTS_BASE_PATH', None)
    cleanup()
