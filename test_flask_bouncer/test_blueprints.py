from functools import wraps
from flask import Flask, Blueprint
from flask_bouncer import Bouncer, ensure, requires
from bouncer.constants import *
import pytest
from .models import Article, TopSecretFile, User
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

def test_monitored_view_on_blueprint():
    app = Flask("monitored_blueprint")
    bouncer = Bouncer(app)

    @bouncer.authorization_method
    def define_authorization(user, they):
        if user.is_admin:
            they.can(READ, Article)

    class ArticleView(object):
        __target_model__ = Article

    bouncer.monitor(ArticleView)

    # endpoint as flask-classy registers it on a blueprint: "<blueprint>.<ViewClass>:<method>"
    bp = Blueprint('bptest', 'bptest')
    bp.add_url_rule("/articles/", "ArticleView:index", lambda: "A bunch of articles")
    app.register_blueprint(bp)

    client = app.test_client()

    with user_set(app, User(name='nancy', admin=False)):
        assert 403 == client.get('/articles/').status_code

    with user_set(app, User(name='jonathan', admin=True)):
        assert b"A bunch of articles" == client.get('/articles/').data

def test_monitored_views_with_same_name_on_blueprints():
    app = Flask("monitored_same_name")
    bouncer = Bouncer(app)

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can(READ, Article)

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated_function

    def make_view(model):
        class ArticleView(object):
            __target_model__ = model

            @decorator
            def index(self):
                return "index"
        return ArticleView

    views = [make_view(TopSecretFile), make_view(Article)]
    bouncer.monitor(*views)

    # flask-classy routes to a method bound to an instance of the view class
    for name, view in zip(('secret', 'articles'), views):
        bp = Blueprint(name, name, url_prefix='/' + name)
        bp.add_url_rule("/", "ArticleView:index", view().index)
        app.register_blueprint(bp)

    client = app.test_client()

    with user_set(app, User(name='nancy', admin=False)):
        assert 403 == client.get('/secret/').status_code
        assert 200 == client.get('/articles/').status_code
