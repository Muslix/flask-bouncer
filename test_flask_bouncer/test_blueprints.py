from flask import Flask, Blueprint
from flask_bouncer import Bouncer, ensure, requires
from bouncer.constants import *
import pytest
from .models import Article, User
from .helpers import user_set

def test_blueprints():
    app = Flask("blueprints")
    app.debug = True
    bouncer = Bouncer(app)

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can('browse', Article)

    bp = Blueprint('bptest', 'bptest')

    @bp.route("/articles")
    @requires('browse', Article)
    def articles_index():
        return "A bunch of articles"

    app.register_blueprint(bp)

    client = app.test_client()

    jonathan = User(name='jonathan', admin=False)
    with user_set(app, jonathan):
        resp = client.get('/articles')
        assert b"A bunch of articles" == resp.data
