import pytest
from flask import Flask, request
from flask_bouncer import Bouncer, requires, skip_authorization, ensure
from bouncer.constants import *
from .models import Article, User
from .helpers import user_set

def test_lock_it_down_raise_exception():
    app = Flask("test_lock_it_down_raise_exception")
    app.debug = True
    bouncer = Bouncer(app, ensure_authorization=True)

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can('browse', Article)

    # Non decorated route -- should be Forbidden
    @app.route("/articles")
    def articles_index():
        return "A bunch of articles"

    client = app.test_client()

    jonathan = User(name='jonathan', admin=False)
    with user_set(app, jonathan):
        resp = client.get('/articles')
        assert 403 == resp.status_code

def test_lock_it_down_without_debug():
    # Flask propagates exceptions only in debug/testing mode, the status codes must also be right without
    app = Flask("test_lock_it_down_without_debug")

    # registered before Bouncer, its responses must be checked as well
    @app.before_request
    def early_response():
        if request.args.get('early'):
            return "early response"

    bouncer = Bouncer(app, ensure_authorization=True)

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can('browse', Article)

    @app.route("/articles")
    def articles_index():
        return "A bunch of articles"

    @app.errorhandler(403)
    def forbidden(e):
        return "custom forbidden", 403

    # registered after Bouncer, its header must not get lost on the 403 response
    @app.after_request
    def add_cors_header(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    client = app.test_client()

    jonathan = User(name='jonathan', admin=False)
    with user_set(app, jonathan):
        resp = client.get('/articles')
        assert (403, b"custom forbidden") == (resp.status_code, resp.data)
        assert '*' == resp.headers.get('Access-Control-Allow-Origin')
        assert 403 == client.get('/articles?early=1').status_code
        assert 404 == client.get('/unknown').status_code

def test_ensure_and_requires_while_locked_down():
    app = Flask("test_ensure_and_requires_while_locked_down")
    app.debug = True
    bouncer = Bouncer(app, ensure_authorization=True)

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can(READ, Article)
        they.can(EDIT, Article, author_id=user.id)

    @app.route("/articles")
    @requires(READ, Article)
    def articles_index():
        return "A bunch of articles"

    @app.route("/article/<int:post_id>", methods=['POST'])
    def edit_post(post_id):
        # Find an article from a db -- faking for testing
        jonathan = User(name='jonathan', admin=False, id=1)
        article = Article(author_id=jonathan.id)

        # bounce them out if they do not have access
        ensure(EDIT, article)
        # edit the post
        return "successfully edited post"

    client = app.test_client()

    jonathan = User(name='jonathan', admin=False, id=1)
    with user_set(app, jonathan):
        resp = client.get('/articles')
        assert b"A bunch of articles" == resp.data

        resp = client.post('/article/1')
        assert b"successfully edited post" == resp.data

def test_bypass_route():
    app = Flask("test_lock_it_down_raise_exception")
    app.debug = True
    bouncer = Bouncer(app, ensure_authorization=True)

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can('browse', Article)

    # Non decorated route -- should raise a Forbidden
    @app.route("/articles")
    @skip_authorization
    def articles_index():
        return "A bunch of articles"

    client = app.test_client()

    jonathan = User(name='jonathan', admin=False)
    with user_set(app, jonathan):
        resp = client.get('/articles')
        assert b"A bunch of articles" == resp.data
