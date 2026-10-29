from flask import Flask, g
from werkzeug.local import LocalProxy
import bouncer as plain_bouncer
from flask_bouncer import Bouncer, ensure, can, get_ability, clear_abilities
from bouncer.constants import *
from .models import Article, User
from .helpers import user_set


def make_app():
    app = Flask("get_ability")
    bouncer = Bouncer(app)
    app.builds = []

    @bouncer.authorization_method
    def define_authorization(user, they):
        app.builds.append(user)
        they.can(READ, Article)
        they.can(EDIT, Article, lambda article: article.author_id == user.id)

    return app

def test_rules_are_built_once_per_request():
    app = make_app()

    @app.route("/article/<int:author_id>")
    def edit_article(author_id):
        ensure(READ, Article)
        # conditions are still evaluated per subject
        return "%s %s" % (can(EDIT, Article(author_id=author_id)), can(EDIT, Article(author_id=0)))

    client = app.test_client()

    with user_set(app, User(name='jonathan', admin=False, id=1)):
        assert b"True False" == client.get('/article/1').data
        assert 1 == len(app.builds)

        client.get('/article/1')
        assert 2 == len(app.builds)

def test_cache_does_not_outlive_the_request():
    app = make_app()

    # requests reuse an app context that is already pushed, so g is shared between them
    with app.app_context():
        g.current_user = User(name='jonathan', admin=False)
        for _ in range(2):
            with app.test_request_context():
                can(READ, Article)

    assert 2 == len(app.builds)

def test_clear_abilities():
    app = make_app()

    with app.test_request_context():
        g.current_user = User(name='jonathan', admin=False)
        can(READ, Article)
        clear_abilities()
        can(READ, Article)

    assert 2 == len(app.builds)

def test_proxy_is_cached_per_real_user():
    app = make_app()
    jonathan = User(name='jonathan', admin=False, id=1)
    nancy = User(name='nancy', admin=False, id=2)
    current = [jonathan]
    current_user = LocalProxy(lambda: current[0])

    with app.test_request_context():
        assert get_ability(current_user) is get_ability(jonathan)
        current[0] = nancy
        assert get_ability(current_user) is get_ability(nancy)
        assert get_ability(nancy) is not get_ability(jonathan)

        # the rules stay bound to jonathan, not to whoever the proxy points to now
        assert get_ability(jonathan).can(EDIT, Article(author_id=jonathan.id))
        assert not get_ability(jonathan).can(EDIT, Article(author_id=nancy.id))

def test_global_authorization_method_is_ignored():
    plain_bouncer.authorization_method(lambda user, they: they.can(MANAGE, ALL))
    try:
        app = make_app()
        with app.test_request_context():
            g.current_user = User(name='jonathan', admin=False)
            assert not can(DELETE, Article)
    finally:
        plain_bouncer.authorization_method(None)

def test_stops_at_first_matching_condition():
    app = Flask("first_match")
    bouncer = Bouncer(app)
    calls = []

    def condition(name):
        def check(article):
            calls.append(name)
            return True
        return check

    @bouncer.authorization_method
    def define_authorization(user, they):
        they.can(EDIT, Article, condition('first'))
        they.can(EDIT, Article, condition('last'))

    with app.test_request_context():
        g.current_user = User(name='jonathan', admin=False)
        assert can(EDIT, Article(author_id=1))

    # later rules take precedence, the earlier one is not evaluated anymore
    assert ['last'] == calls

def check(rules, action, subject):
    app = Flask("class_subjects")
    bouncer = Bouncer(app)
    bouncer.authorization_method(lambda user, they: rules(they))
    with app.test_request_context():
        g.current_user = User(name='jonathan', admin=False)
        return can(action, subject)

def test_conditions_never_allow_a_class():
    # a condition needs an object to decide on
    assert not check(lambda they: they.can(EDIT, Article, lambda article: True), EDIT, Article)
    assert not check(lambda they: they.can(EDIT, Article, author_id=1), EDIT, Article)
    # an unconditional rule still allows the class ...
    assert check(lambda they: (they.can(EDIT, Article), they.can(EDIT, Article, author_id=1)), EDIT, Article)
    # ... and a conditional cannot rule still forbids it
    assert not check(lambda they: (they.can(EDIT, Article), they.cannot(EDIT, Article, author_id=1)), EDIT, Article)

def test_conditions_on_strings_are_evaluated():
    calls = []

    def condition(subject):
        calls.append(subject)
        return True

    assert check(lambda they: they.can(EDIT, 'Article', condition), EDIT, 'Article')
    assert ['Article'] == calls
