"""生产启动：Waitress（Windows）/ Gunicorn（Linux）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.app import app  # noqa: E402

if __name__ == '__main__':
    if os.name == 'nt':
        from waitress import serve
        print(f'服务已启动： http://{app.config["HOST"]}:{app.config["PORT"]}')
        serve(app, host=app.config['HOST'], port=app.config['PORT'], threads=8)
    else:
        from gunicorn.app.base import BaseApplication

        class App(BaseApplication):
            def load_config(self):
                self.cfg.set('bind', f'{app.config["HOST"]}:{app.config["PORT"]}')
                self.cfg.set('workers', 2)
                self.cfg.set('threads', 4)
                self.cfg.set('timeout', 120)

            def load(self):
                return app

        App().run()
