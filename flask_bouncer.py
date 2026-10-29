#!/usr/bin/env python
# -*- coding: utf-8 -*-
import inspect
from functools import wraps

from flask import request, g, current_app, after_this_request, has_app_context, has_request_context
from werkzeug.local import LocalProxy
from werkzeug.exceptions import Forbidden
from bouncer import Ability
from bouncer.constants import *


# Convenient references
_bouncer = LocalProxy(lambda: current_app.extensions['bouncer'])


class _Ability(Ability):

    def can(self, action, subject):
        # unlike Ability.can, stops at the first matching rule instead of evaluating every condition
        # (conditions may run database queries)
        for rule in self.relevant_rules_for_match(action, subject):
            # a condition needs an object to decide on (bouncer treats it as fulfilled for a class):
            # a conditional rule may still forbid a class, but never allow it
            if rule.base_behavior and rule.conditions is not None and inspect.isclass(subject):
                continue
            if rule.matches_conditions(action, subject):
                return rule.base_behavior
        return False


def get_ability(user):
    """Returns the Ability of ``user``. Its rules are built only once per request,
    call ``clear_abilities()`` when permissions change within a request.
    """
    # bind the rules to the real object: a proxy (e.g. flask-jwt's current_identity) can point to another user later
    if isinstance(user, LocalProxy):
        user = user._get_current_object()
    cache = _ability_cache()
    ability = cache.get(id(user))
    if ability is None:
        # the authorization method goes into the constructor, otherwise Ability also applies a globally
        # registered bouncer.authorization_method; ability.user keeps the user alive so its id is not reused
        ability = cache[id(user)] = _Ability(user, _bouncer.get_authorization_method())
    ability.aliased_actions = _bouncer.alias_actions
    return ability


def _ability_cache():
    # stored on the request, not on g: the app context (and g) can span several requests in tests, CLI and workers
    if not has_request_context():
        return {}
    if not hasattr(request, '_bouncer_abilities'):
        request._bouncer_abilities = {}
    return request._bouncer_abilities


def clear_abilities():
    """Forgets the Abilities cached for the current request, e.g. after roles were changed."""
    if has_request_context():
        request._bouncer_abilities = {}


def ensure(action, subject):
    request._authorized = True
    current_user = _bouncer.get_current_user()
    if get_ability(current_user).cannot(action, subject):
        # details only in the debug log: the reprs of user and subject can contain data the user may not
        # read (the description ends up in the response body, e.g. as flask-restful's "message")
        current_app.logger.debug("%s does not have %s access to %s", current_user, action, subject)
        raise Forbidden()


def can(action, subject):
    request._authorized = True
    return get_ability(_bouncer.get_current_user()).can(action, subject)


# alias
bounce = ensure


class Condition(object):

    def __init__(self, action, subject):
        self.action = action
        self.subject = subject

    def test(self):
        ensure(self.action, self.subject)


def requires(action, subject):
    def decorator(f):
        f._explict_rule_set = True

        @wraps(f)
        def decorated_function(*args, **kwargs):
            Condition(action, subject).test()
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def skip_authorization(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        request._authorized = True
        return f(*args, **kwargs)
    return decorated_function


class Bouncer(object):

    """This class is used to control the Abilities Integration to one or more Flask applications"""

    special_methods = ["get", "put", "patch", "post", "delete", "index"]

    def __init__(self, app=None, **kwargs):

        self._alias_actions = self.default_alias_actions()
        self._authorization_method = None
        self.flask_classy_classes = list()
        self.get_current_user = self.default_user_loader

        self.app = None

        if app is not None:
            self.init_app(app, **kwargs)

    def get_app(self, reference_app=None):
        """Helper method that implements the logic to look up an application."""

        if reference_app is not None:
            return reference_app

        if self.app is not None:
            return self.app

        if has_app_context():
            return current_app._get_current_object()

        raise RuntimeError('Application not registered on Bouncer'
                           ' instance and no application bound'
                           ' to current context')

    def init_app(self, app, **kwargs):
        """ Initializes the Flask-Bouncer extension for the specified application.

        :param app: The application.
        """
        self.app = app

        self._init_extension()

        self.app.before_request(self.check_implicit_rules)

        if kwargs.get('ensure_authorization', False):
            # first before_request handler, so responses returned by other handlers are checked as well
            self.app.before_request_funcs.setdefault(None, []).insert(0, self._register_authorization_check)

    def _register_authorization_check(self):
        # after_this_request callbacks run before all after_request handlers (app and blueprints),
        # so headers and cookies they add (e.g. CORS) end up on the 403 response
        after_this_request(self.check_authorization)

    def _init_extension(self):
        if not hasattr(self.app, 'extensions'):
            self.app.extensions = dict()

        self.app.extensions['bouncer'] = self

    def check_authorization(self, response):
        """checks that an authorization call has been made during the request"""
        if getattr(request, '_authorized', False) or request.routing_exception is not None:
            # no route matched (404, 405, ...): no view ran, keep the routing error
            return response
        # an exception raised while processing the response is not handled by Flask and ends as a 500,
        # so build the 403 response here, using the app's error handler if one is registered
        return current_app.make_response(current_app.handle_http_exception(Forbidden()))

    def check_implicit_rules(self):
        """ if you are using flask classy are using the standard index,new,put,post, etc ... type routes, we will
            automatically check the permissions for you
        """
        if not self.request_is_managed_by_flask_classy():
            return

        if self.method_is_explictly_overwritten():
            return

        class_name, action = self._classy_endpoint()
        candidates = [classy_class for classy_class in self.flask_classy_classes if classy_class.__name__ == class_name]
        # classes with the same name on different blueprints: take the class the view method is bound to,
        # if that is unknown (decorator without functools.wraps) every candidate has to allow it.
        # stop at the bound method, its __wrapped__ (from a decorated method) leads to the plain function
        view_self = getattr(inspect.unwrap(current_app.view_functions[request.endpoint],
                                           stop=lambda f: hasattr(f, '__self__')), '__self__', None)
        for clazz in [c for c in candidates if type(view_self) is c] or candidates:
            Condition(action, clazz.__target_model__).test()

    def method_is_explictly_overwritten(self):
        view_func = current_app.view_functions[request.endpoint]
        return hasattr(view_func, '_explict_rule_set') and view_func._explict_rule_set is True

    def request_is_managed_by_flask_classy(self):
        if request.endpoint is None:
            return False
        if ':' not in request.endpoint:
            return False
        class_name, action = self._classy_endpoint()
        return any(class_name == classy_class.__name__ for classy_class in self.flask_classy_classes) \
            and action in self.special_methods

    def _classy_endpoint(self):
        # strips blueprint prefixes: "bp.ArticleView:index" -> ("ArticleView", "index")
        class_name, _, action = request.endpoint.rpartition('.')[2].partition(':')
        return class_name, action

    def default_user_loader(self):
        if hasattr(g, 'current_user'):
            return g.current_user
        elif hasattr(g, 'user'):
            return g.user
        else:
            raise Exception("Excepting current_user on flask's g")

    def user_loader(self, value):
        """
        Use this method decorator to overwrite the default user loader
        """
        self.get_current_user = value
        return value

    @property
    def alias_actions(self):
        return self._alias_actions

    @alias_actions.setter
    def alias_actions(self, value):
        """if you want to override your actions"""
        self._alias_actions = value

    def default_alias_actions(self):
        return {
            READ: [INDEX, SHOW, GET],
            CREATE: [NEW, PUT, POST],
            UPDATE: [EDIT, PATCH]
        }

    def monitor(self, *classy_routes):
        self.flask_classy_classes.extend(classy_routes)

    def authorization_method(self, value):
        """
        the callback for defining user abilities
        """
        self._authorization_method = value
        return self._authorization_method

    def get_authorization_method(self):
        if self._authorization_method is not None:
            return self._authorization_method
        else:
            raise Exception('Expected authorication method to be set')
