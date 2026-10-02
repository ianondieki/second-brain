"""Every in-app notification links to a platform path (REQ-NOT-03, task P19-C; docs/spec/07 §1: the bell).

The bell's page makes each row a link to its ``link``. ``post_in_app`` refuses anything but a platform path at run
time; this test proves it from the source for every writer of ``in_app_notifications``: each ``post_in_app`` call,
each ``InAppNotification(...)`` row and each raw ``INSERT INTO in_app_notifications``, so the writers that do not go
through ``post_in_app`` (the tracker's ``notify._in_app``, the pitch receipt in ``proposals/tags.py``) are held to the
same rule. A link is followed back to where it is made, through local variables, module constants, a function's
parameter (every call of the function) and a parameter's class field (every construction of the class), and must end
in one of: None; a literal path or f-string whose text starts with ``/`` and a letter (so no value can make it
``//host``); ``CONSTANT.format(...)`` of such a literal; or a builder of ``bridge.web_paths``, which is called here.
Anything else fails: make the link with ``bridge.web_paths`` or a literal path.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest

import bridge
from bridge import web_paths
from bridge.models.enums import EngagementParty
from bridge.notifications.in_app import MAX_LINK_CHARS, is_platform_path

SRC = Path(bridge.__file__).resolve().parent
TRUSTED_MODULE = "bridge.web_paths"
PATH_HEAD = re.compile(r"/[a-z]")  # a literal's own text starts the path: a value after it cannot make "//host"
INSERT_IN_APP = re.compile(r"INSERT\s+INTO\s+in_app_notifications\b", re.IGNORECASE)
Func = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class Module:
    name: str
    rel: str
    tree: ast.Module
    enclosing: dict[int, Func] = field(default_factory=dict)  # id(node) -> the innermost function around it
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # local name -> (module, name)

    def __post_init__(self) -> None:
        def visit(node: ast.AST, around: Func | None) -> None:
            for child in ast.iter_child_nodes(node):
                if around is not None:
                    self.enclosing[id(child)] = around
                visit(child, child if isinstance(child, Func) else around)

        visit(self.tree, None)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (node.module, alias.name)

    def where(self, node: ast.AST) -> str:
        return f"{self.rel}:{getattr(node, 'lineno', '?')}"


def load(root: Path = SRC) -> dict[str, Module]:
    modules = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        modules[name] = Module(name, str(path.relative_to(root.parent)), ast.parse(path.read_text(encoding="utf-8")))
    return modules


def callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    return call.func.attr if isinstance(call.func, ast.Attribute) else None


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


@dataclass(frozen=True)
class Site:
    """One writer of in_app_notifications and the expression its link comes from."""

    module: Module
    link: ast.expr
    where: str


def writers(modules: dict[str, Module]) -> list[Site]:
    found = []
    for module in modules.values():
        insert_names = set()
        for top in module.tree.body:  # raw SQL held in a module constant: NAME = text("INSERT INTO ...")
            if isinstance(top, ast.Assign) and any(
                isinstance(c, ast.Constant) and isinstance(c.value, str) and INSERT_IN_APP.search(c.value)
                for c in ast.walk(top.value)
            ):
                insert_names |= {t.id for t in top.targets if isinstance(t, ast.Name)}
        for call in ast.walk(module.tree):
            if not isinstance(call, ast.Call):
                continue
            if callee(call) in ("post_in_app", "InAppNotification"):
                link = keyword(call, "link")
                found.append(Site(module, link if link is not None else ast.Constant(None), module.where(call)))
            elif any(isinstance(a, ast.Name) and a.id in insert_names for a in call.args):
                values = [a for a in call.args if isinstance(a, ast.Dict)]
                link = next(
                    (v for d in values for k, v in zip(d.keys, d.values, strict=True) if _is(k, "link")),
                    ast.Name("<no link parameter>"),
                )
                found.append(Site(module, link, module.where(call)))
    return found


def _is(node: ast.expr | None, text: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == text


def _template_ok(text: str) -> bool:
    return PATH_HEAD.match(text) is not None and is_platform_path(re.sub(r"\{[^}]*\}", "x", text))


class Resolver:
    """Follows a link expression to where it is made; ``check`` lists what could not be proved a platform path."""

    def __init__(self, modules: dict[str, Module]) -> None:
        self.modules = modules
        self.seen: set[tuple[str, int]] = set()

    def check(self, expr: ast.expr, module: Module) -> list[str]:
        if (module.name, id(expr)) in self.seen:
            return []
        self.seen.add((module.name, id(expr)))
        if isinstance(expr, ast.Constant) and (expr.value is None or isinstance(expr.value, str)):
            return [] if expr.value is None or is_platform_path(expr.value) else [self._bad(expr, module)]
        if isinstance(expr, ast.JoinedStr):
            text = "".join(str(v.value) if isinstance(v, ast.Constant) else "{}" for v in expr.values)
            return [] if _template_ok(text) else [self._bad(expr, module)]
        if isinstance(expr, ast.IfExp):
            return self.check(expr.body, module) + self.check(expr.orelse, module)
        if isinstance(expr, ast.Call):
            return self._call(expr, module)
        if isinstance(expr, ast.Name):
            return self._name(expr, module)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            return self._field(expr, module)
        return [self._bad(expr, module)]

    def _bad(self, expr: ast.expr, module: Module) -> str:
        return f"{module.where(expr)}: cannot prove `{ast.unparse(expr)}` is a platform path"

    def _trusted(self, module: Module, name: str) -> bool:
        return module.name == TRUSTED_MODULE or module.imports.get(name, ("", ""))[0] == TRUSTED_MODULE

    def _call(self, call: ast.Call, module: Module) -> list[str]:
        if isinstance(call.func, ast.Name) and self._trusted(module, call.func.id):
            return []
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "format" and isinstance(func.value, ast.Name):
            template = self._constant(func.value.id, module)
            if template is not None and _template_ok(template):
                return []
        return [self._bad(call, module)]

    def _constant(self, name: str, module: Module) -> str | None:
        for node in module.tree.body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            named = any(isinstance(t, ast.Name) and t.id == name for t in _targets(node))
            if named and isinstance(node.value, ast.Constant):
                return node.value.value if isinstance(node.value.value, str) else None
        source = module.imports.get(name)
        return self._constant(source[1], self.modules[source[0]]) if source and source[0] in self.modules else None

    def _name(self, expr: ast.Name, module: Module) -> list[str]:
        if self._trusted(module, expr.id):
            return []
        func = module.enclosing.get(id(expr))
        scope: list[ast.stmt] = list(func.body) if func is not None else module.tree.body
        values = [
            node.value
            for top in scope
            for node in ast.walk(top)
            if isinstance(node, ast.Assign | ast.AnnAssign)
            and node.value is not None
            and any(isinstance(t, ast.Name) and t.id == expr.id for t in _targets(node))
        ]
        problems = [p for value in values for p in self.check(value, module)]
        if func is not None and expr.id in _params(func):
            calls = self._calls_of(func.name, module)
            if not calls:
                problems.append(f"{module.where(expr)}: no call of {func.name}() to follow `{expr.id}` into")
            for caller, call in calls:
                argument = _argument(call, func, expr.id)
                problems += [self._bad(expr, module)] if argument is None else self.check(argument, caller)
        elif not values:
            template = self._constant(expr.id, module)
            problems += [] if template is not None and is_platform_path(template) else [self._bad(expr, module)]
        return problems

    def _field(self, expr: ast.Attribute, module: Module) -> list[str]:
        """``param.field``: the field of every construction of the parameter's annotated class."""
        func = module.enclosing.get(id(expr))
        arg = next((a for a in _all_args(func) if a.arg == getattr(expr.value, "id", None)), None) if func else None
        if arg is None or not isinstance(arg.annotation, ast.Name | ast.Constant):
            return [self._bad(expr, module)]
        cls_name = arg.annotation.id if isinstance(arg.annotation, ast.Name) else str(arg.annotation.value)
        cls = next((n for n in module.tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name), None)
        if cls is None:
            return [self._bad(expr, module)]
        fields = [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
        if expr.attr not in fields:
            return [self._bad(expr, module)]
        made = self._calls_of(cls_name, module)
        if not made:
            return [f"{module.where(expr)}: no {cls_name}(...) found to follow `{ast.unparse(expr)}` into"]
        problems = []
        for maker, call in made:
            given = keyword(call, expr.attr)
            index = fields.index(expr.attr)
            if given is None and index < len(call.args) and not any(isinstance(a, ast.Starred) for a in call.args):
                given = call.args[index]
            problems += [self._bad(expr, maker)] if given is None else self.check(given, maker)
        return problems

    def _calls_of(self, name: str, home: Module) -> list[tuple[Module, ast.Call]]:
        """Calls of ``home``'s ``name`` in ``home`` and in every module that imports it by name."""
        return [
            (module, node)
            for module in self.modules.values()
            if module is home or module.imports.get(name) == (home.name, name)
            for node in ast.walk(module.tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        ]


def _targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _all_args(func: Func | None) -> list[ast.arg]:
    if func is None:
        return []
    return [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]


def _params(func: Func) -> set[str]:
    return {a.arg for a in _all_args(func)}


def _argument(call: ast.Call, func: Func, name: str) -> ast.expr | None:
    given = keyword(call, name)
    positional = [a.arg for a in (*func.args.posonlyargs, *func.args.args)]
    if given is None and name in positional and positional.index(name) < len(call.args):
        given = call.args[positional.index(name)]
    return given


MODULES = load()
SITES = writers(MODULES)


def test_the_scan_finds_every_known_writer() -> None:
    """At least these (a new writer is checked below without being listed here)."""
    found = Counter(site.module.name for site in SITES)
    assert found >= Counter(
        {
            "bridge.notifications.in_app": 1,  # post_in_app's own row (its callers' links, followed below)
            "bridge.engagements.notify": 1,  # the tracker's notices (notify._in_app)
            "bridge.engagements.interest": 1,  # a Tier-2 share told to the organisation
            "bridge.matching.digest": 1,  # EM3, the scouts' digest
            "bridge.reminders.dispatch": 2,  # EM7 nudge and the organisation's digest
            "bridge.proposals.tags": 1,  # the pitch receipt (raw SQL)
        }
    )


@pytest.mark.parametrize("site", SITES, ids=[site.where for site in SITES])
def test_every_writer_links_to_a_platform_path(site: Site) -> None:
    problems = Resolver(MODULES).check(site.link, site.module)
    assert not problems, "\n".join(problems)


def test_every_web_paths_builder_makes_a_platform_path() -> None:
    """The scan trusts ``bridge.web_paths``: each of its builders and constants is checked here."""
    public = {
        name
        for name, value in vars(web_paths).items()
        if (callable(value) and getattr(value, "__module__", None) == TRUSTED_MODULE)
        or (name.isupper() and isinstance(value, str))
    }
    made = {
        "engagement_path": [web_paths.engagement_path(party, uuid4()) for party in EngagementParty],
        "org_engagements_path": [web_paths.org_engagements_path(uuid4())],
        "DEV_ENGAGEMENTS": [web_paths.DEV_ENGAGEMENTS],
        "ORG_ENGAGEMENTS": [web_paths.ORG_ENGAGEMENTS],
    }
    assert set(made) == public  # a new builder is added here before a writer may use it
    assert all(is_platform_path(link) for links in made.values() for link in links)


BAD_WRITERS = {
    "an absolute URL": 'post_in_app(db, link="https://evil.example/x")',
    "a base URL first": 'post_in_app(db, link=f"{base}/dev/x")',
    "a value first": 'post_in_app(db, link=f"/{where}")',
    "an unproved value": "def f(db, request):\n    post_in_app(db, link=request.query)",
    "a parameter's bad caller": 'def send(db, link):\n    post_in_app(db, link=link)\nsend(db, "//evil.example")',
    "a field's bad construction": (
        "class Notice:\n    link: str\n"
        "def tell(db, notice: Notice):\n    InAppNotification(link=notice.link)\n"
        'Notice("//evil.example")'
    ),
    "raw SQL without a proved link": (
        'Q = text("INSERT INTO in_app_notifications (id, link) VALUES (:id, :link)")\n'
        "def f(db, url):\n    db.execute(Q, {'id': 1, 'link': url})"
    ),
}
GOOD_WRITERS = {
    "a literal": 'post_in_app(db, link="/dev/engagements")',
    "an f-string": 'post_in_app(db, link=f"/dev/ideas/{proposal_id}")',
    "no link": "post_in_app(db, link=None)",
    "a template constant": 'T = "/org/inbox?org={org}"\ndef f(db, org):\n    post_in_app(db, link=T.format(org=org))',
    "a parameter's good caller": 'def send(db, link):\n    post_in_app(db, link=link)\nsend(db, "/dev/engagements")',
}


def _scan(source: str) -> list[str]:
    module = Module("bridge.fake", "bridge/fake.py", ast.parse(source))
    modules = {module.name: module}
    sites = writers(modules)
    assert sites
    return [problem for site in sites for problem in Resolver(modules).check(site.link, site.module)]


@pytest.mark.parametrize("source", BAD_WRITERS.values(), ids=BAD_WRITERS.keys())
def test_the_scan_refuses_a_link_it_cannot_prove(source: str) -> None:
    assert _scan(source)


@pytest.mark.parametrize("source", GOOD_WRITERS.values(), ids=GOOD_WRITERS.keys())
def test_the_scan_accepts_a_proved_link(source: str) -> None:
    assert _scan(source) == []


@pytest.mark.parametrize(
    "link", ["/", "/dev/engagements", "/org/engagements?org=1f0c", "/org/inbox?org=x&tab=matches", "/dev/ideas/a#b"]
)
def test_a_platform_path(link: str) -> None:
    assert is_platform_path(link)


@pytest.mark.parametrize(
    "link",
    [
        "",
        "dev/engagements",
        "https://evil.example/x",
        "//evil.example",
        "/\\evil.example",
        "/\\/evil.example",
        "/\t/evil.example",
        "/\n/evil.example",
        "/a b",
        "/a\x7f",
        "/" + "a" * MAX_LINK_CHARS,
    ],
)
def test_not_a_platform_path(link: str) -> None:
    assert not is_platform_path(link)
