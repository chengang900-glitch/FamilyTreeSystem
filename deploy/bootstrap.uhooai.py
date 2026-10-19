"""One-time empty-volume initialization; never emit the bootstrap password."""
import contextlib
import io
import os
from pathlib import Path

os.environ['FTS_ADMIN_PASSWORD'] = Path('/run/secrets/admin_password').read_text().strip()
# The upstream app prints its generated/provided initial password on first import.
with contextlib.redirect_stdout(io.StringIO()):
    from server.app import app
    from server.service.auth import _secret
    with app.app_context():
        _secret()
print('Initialized familytree database and persistent signing key.')
