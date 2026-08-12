"""
Vantage6 Node Manager Web Application
A Flask-based web interface for managing vantage6 nodes
"""
import os
from flask import Flask

from nodemanager import auth
from nodemanager.auth import auth_bp
from nodemanager.nodes import nodes_bp
from nodemanager.node_actions import actions_bp
from nodemanager.api import api_bp

app = Flask(__name__)
# Mitigates CSRF on the existing unprotected forms (node create/delete/etc.):
# a cross-site POST can no longer ride along with the session cookie. Full
# CSRF tokens (Flask-WTF) remain a deferred follow-up.
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

auth.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(nodes_bp)
app.register_blueprint(actions_bp)
app.register_blueprint(api_bp)


if __name__ == '__main__':
    # Opt-in only: the Werkzeug debugger is unauthenticated WSGI middleware
    # that runs before Flask routing (and thus before the before_request
    # login gate), and this app has /var/run/docker.sock mounted - it must
    # default OFF rather than default-on-unless-production.
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
