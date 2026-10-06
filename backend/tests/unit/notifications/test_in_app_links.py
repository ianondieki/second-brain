"""Every in-app notification links to a platform path (REQ-NOT-03, task P19-C; docs/spec/07 §1: the bell).

The bell's page makes each row a link to its ``link``. ``post_in_app`` refuses anything but a platform path at run
time; this test proves it from the source for every writer of ``in_app_notifications``: each ``post_in_app`` call,
each ``InAppNotification(...)`` row, each ``insert(InAppNotification)`` and each SQL ``INSERT INTO
in_app_notifications`` (held in a constant or a variable, or inline in ``text(...)``), under any import alias, so the
writers that do not go through ``post_in_app`` (the tracker's ``notify._in_app``, the pitch receipt in
``proposals/tags.py``) are held to the same rule. A writer must name its link (``link=``, or the statement's
``"link"`` parameter); ``*args``, ``**kwargs`` or a missing link is unproved. A link is followed back to where it is
made, through local variables, module constants, a function's parameter (every call of the function) and a
parameter's class field (every construction of the class), and must end in one of: None; a literal path or f-string
whose text starts with ``/`` and a letter (so no value can make it ``//host``); ``CONSTANT.format(...)`` of such a
literal; or a builder of ``bridge.web_paths``, which is called here. Anything else fails: make the link with
``bridge.web_paths`` or a literal path.
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
LINK_COLUMN = re.compile(r"\blink\b", re.IGNORECASE)
WRITER_CALLS = frozenset({"post_in_app", "InAppNotification"})
MODEL = "InAppNotification"
Func = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class Module:
    name: str
    rel: str
    tree: ast.Module
    enclosing: dict[int, Func] = field(default_factory=dict)  # id(node) -> the innermost function around it
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # local name -> (module, name)
    module_aliases: dict[str, str] = field(default_factory=dict)  # import a.b as c: c -> a.b
    parents: dict[int, ast.AST] = field(default_factory=dict)  # id(node) -> its parent

    def __post_init__(self) -> None:
        def visit(node: ast.AST, around: Func | None) -> None:
            for child in ast.iter_child_nodes(node):
                self.parents[id(child)] = node
                if around is not None:
                    self.enclosing[id(child)] = around
                visit(child, child if isinstance(child, Func) else around)

        visit(self.tree, None)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (node.module, alias.name)
            elif isinstance(node, ast.Import):
                self.module_aliases |= {a.asname: a.name for a in node.names if a.asname}

    def names_module(self, node: ast.expr, target: str) -> bool:
        """Whether ``node`` is a name bound to the module ``target`` (``from a import b``, ``import a.b as c``)."""
        if not isinstance(node, ast.Name):
            return False
        return self.module_aliases.get(node.id) == target or ".".join(self.imports.get(node.id, ("", ""))) == target

    def original(self, node: ast.expr, depth: int = 0) -> str | None:
        """The name ``node`` stands for, an alias followed: ``tell`` for ``post_in_app as tell``, ``N`` for a module's
        ``N = InAppNotification``."""
        if isinstance(node, ast.Attribute):
            return node.attr
        if not isinstance(node, ast.Name):
            return None
        if node.id in self.imports:
            return self.imports[node.id][1]
        for top in self.tree.body:
            if (
                depth < 5
                and isinstance(top, ast.Assign)
                and isinstance(top.value, ast.Name | ast.Attribute)
                and any(isinstance(t, ast.Name) and t.id == node.id for t in top.targets)
            ):
                return self.original(top.value, depth + 1)
        return node.id

    def where(self, node: ast.AST) -> str:
        return f"{self.rel}:{getattr(node, 'lineno', '?')}"


def load(root: Path = SRC) -> dict[str, Module]:
    modules = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        modules[name] = Module(name, str(path.relative_to(root.parent)), ast.parse(path.read_text(encoding="utf-8")))
    return modules


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def unpacked(call: ast.Call) -> bool:
    return any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords)


@dataclass(frozen=True)
class Site:
    """One writer of in_app_notifications and the expression its link comes from, or why it has none proved."""

    module: Module
    link: ast.expr | None
    where: str
    problem: str | None = None


def _site(module: Module, node: ast.AST, link: ast.expr | None, problem: str) -> Site:
    where = module.where(node)
    return Site(module, link, where, None if link is not None else f"{where}: {problem}")


def _named_link(module: Module, call: ast.Call, what: str) -> Site:
    """``link=`` of a call; ``*args``, ``**kwargs`` or no ``link=`` is unproved."""
    if unpacked(call):
        return _site(module, call, None, f"{what} unpacks *args or **kwargs, so its link is unproved")
    return _site(module, call, keyword(call, "link"), f"{what} names no link= (pass link=None for none)")


def _parameters_link(module: Module, call: ast.Call, names_link: bool) -> Site:
    """The ``"link"`` parameter a statement runs with (a dict, or ``bindparams(link=...)``)."""
    dicts = [a for a in call.args if isinstance(a, ast.Dict)]
    if unpacked(call) or any(k is None for d in dicts for k in d.keys):
        return _site(module, call, None, "the INSERT's parameters are unpacked, so its link is unproved")
    given = keyword(call, "link")
    given = given or next((v for d in dicts for k, v in zip(d.keys, d.values, strict=True) if _is(k, "link")), None)
    if given is None and not names_link:
        given = ast.Constant(None)  # the statement writes no link at all
    return _site(module, call, given, "the INSERT names the link column but no 'link' parameter")


def _sql_sites(module: Module) -> list[Site]:
    """Each run of an ``INSERT INTO in_app_notifications``: inline, or held in a variable and run where it is used."""
    pending: list[tuple[ast.AST, bool]] = [
        (node, LINK_COLUMN.search(node.value) is not None)
        for node in ast.walk(module.tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and INSERT_IN_APP.search(node.value)
        if not isinstance(module.parents.get(id(node)), ast.Expr)  # a docstring runs nothing
    ]
    held: set[str] = set()
    sites = []
    while pending:
        start, names_link = pending.pop()
        node: ast.AST = start
        while (parent := module.parents.get(id(node))) is not None:
            if isinstance(parent, ast.Assign | ast.AnnAssign):
                names = [t.id for t in _targets(parent) if isinstance(t, ast.Name)]
                if not names:
                    sites.append(_site(module, start, None, "an INSERT held where the scan cannot follow it"))
                for name in set(names) - held:  # every use of the variable runs it
                    held.add(name)
                    pending += [
                        (use, names_link)
                        for use in ast.walk(module.tree)
                        if isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load)
                    ]
                break
            if isinstance(parent, ast.Call) and (
                keyword(parent, "link") is not None
                or unpacked(parent)
                or any(isinstance(a, ast.Dict) for a in parent.args)
            ):
                sites.append(_parameters_link(module, parent, names_link))
                break
            if isinstance(parent, ast.stmt):
                sites.append(_site(module, start, None, "an INSERT run without literal parameters"))
                break
            node = parent
    return sites


def _names_model(module: Module, node: ast.expr) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "__table__":
        return _names_model(module, node.value)
    return module.original(node) == MODEL


def _insert_sites(module: Module) -> list[Site]:
    """``insert(InAppNotification)`` and ``InAppNotification.__table__.insert()``, each with its ``.values`` link."""
    sites = []
    for call in ast.walk(module.tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        core = isinstance(func, ast.Attribute) and func.attr == "insert" and _names_model(module, func.value)
        orm = module.original(func) == "insert" and bool(call.args) and _names_model(module, call.args[0])
        if not (core or orm):
            continue
        attribute = module.parents.get(id(call))
        values = module.parents.get(id(attribute))
        if isinstance(attribute, ast.Attribute) and attribute.attr == "values" and isinstance(values, ast.Call):
            sites.append(_parameters_link(module, values, names_link=True))
        else:
            sites.append(_site(module, call, None, "insert(InAppNotification) without .values(link=...)"))
    return sites


def writers(modules: dict[str, Module]) -> list[Site]:
    found = []
    for module in modules.values():
        for call in ast.walk(module.tree):
            if isinstance(call, ast.Call) and module.original(call.func) in WRITER_CALLS:
                found.append(_named_link(module, call, f"{ast.unparse(call.func)}(...)"))
        found += _sql_sites(module) + _insert_sites(module)
    return found


def problems_of(site: Site, modules: dict[str, Module]) -> list[str]:
    if site.problem is not None or site.link is None:
        return [site.problem or f"{site.where}: no link"]
    return Resolver(modules).check(site.link, site.module)


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
        if isinstance(expr, ast.Attribute) and module.names_module(expr.value, TRUSTED_MODULE):
            return []  # web_paths.DEV_ENGAGEMENTS
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            return self._field(expr, module)
        return [self._bad(expr, module)]

    def _bad(self, expr: ast.expr, module: Module) -> str:
        return f"{module.where(expr)}: cannot prove `{ast.unparse(expr)}` is a platform path"

    def _trusted(self, module: Module, name: str) -> bool:
        return module.name == TRUSTED_MODULE or module.imports.get(name, ("", ""))[0] == TRUSTED_MODULE

    def _call(self, call: ast.Call, module: Module) -> list[str]:
        func = call.func
        if isinstance(func, ast.Name) and self._trusted(module, func.id):
            return []
        if isinstance(func, ast.Attribute) and module.names_module(func.value, TRUSTED_MODULE):
            return []  # web_paths.engagement_path(...)
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
        """Calls of ``home``'s ``name`` anywhere: by its name in ``home``, by any alias it is imported under, and as an
        attribute of ``home`` imported as a module."""
        found = []
        for module in self.modules.values():
            local = {alias for alias, source in module.imports.items() if source == (home.name, name)}
            if module is home and name not in module.imports:
                local.add(name)
            for node in ast.walk(module.tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Name) and func.id in local) or (
                    isinstance(func, ast.Attribute) and func.attr == name and module.names_module(func.value, home.name)
                ):
                    found.append((module, node))
        return found


def _targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _all_args(func: Func | None) -> list[ast.arg]:
    if func is None:
        return []
    return [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]


def _params(func: Func) -> set[str]:
    return {a.arg for a in _all_args(func)}


def _argument(call: ast.Call, func: Func, name: str) -> ast.expr | None:
    """The argument a call passes for ``name``; None when it is not given or hidden in ``*args``/``**kwargs``."""
    given = keyword(call, name)
    positional = [a.arg for a in (*func.args.posonlyargs, *func.args.args)]
    if given is None and not unpacked(call) and name in positional and positional.index(name) < len(call.args):
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
    problems = problems_of(site, MODULES)
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
        "messages_path": [web_paths.messages_path(party, uuid4()) for party in EngagementParty],
        "DEV_ENGAGEMENTS": [web_paths.DEV_ENGAGEMENTS],
        "ORG_ENGAGEMENTS": [web_paths.ORG_ENGAGEMENTS],
        "DEV_DISCOVER": [web_paths.DEV_DISCOVER],
        "dev_event_path": [web_paths.dev_event_path(uuid4())],  # P22 track B: N27, the morning-of notice
        "discover_path": [  # P21 track C: a saved search's alert; values are query-encoded, too-long words left out
            web_paths.discover_path(view, niche=niche, county=county, words=words)
            for view in ("problems", "briefs")
            for niche, county, words in (
                (None, None, None),
                ("agri-x", "KE-32", "//evil.example/ \\x?a=b#c"),
                (None, None, "\U0001f33e" * 200),
            )
        ],
    }
    assert set(made) == public  # a new builder is added here before a writer may use it
    assert all(is_platform_path(link) for links in made.values() for link in links)


UNPROVED = "def f(db, url):\n    "
SQL = "INSERT INTO in_app_notifications (id, link) VALUES (:id, :link)"
BAD_WRITERS: dict[str, str | tuple[str, str]] = {
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
    "raw SQL in a constant without a proved link": (
        f'Q = text("{SQL}")\n{UNPROVED}db.execute(Q, {{"id": 1, "link": url}})'
    ),
    "**kwargs": "def f(db, kwargs):\n    post_in_app(db, **kwargs)",
    "**kwargs beside a good link": 'def f(db, kwargs):\n    post_in_app(db, link="/dev/x", **kwargs)',
    "*args to the model": "def f(row):\n    InAppNotification(*row)",
    "no link= to post_in_app": 'post_in_app(db, user_id=u, title="Approved")',
    "no link= to the model": 'InAppNotification(user_id=u, title="Approved")',
    "a parameter hidden in **kwargs": 'def send(db, link):\n    post_in_app(db, link=link)\nsend(db, **{"link": "/x"})',
    "insert(...).values(link=unproved)": f"{UNPROVED}db.execute(insert(InAppNotification).values(user_id=1, link=url))",
    "insert(...).values({...}) unproved": f'{UNPROVED}db.execute(insert(InAppNotification).values({{"link": url}}))',
    "insert(...) without .values": "def f(db, rows):\n    db.execute(insert(InAppNotification), rows)",
    "insert(...).values() without link": "def f(db):\n    db.execute(insert(InAppNotification).values(user_id=1))",
    "an aliased insert of the table": (
        "from sqlalchemy.dialects.postgresql import insert as upsert\n"
        f"{UNPROVED}db.execute(upsert(InAppNotification.__table__).values(link=url))"
    ),
    "__table__.insert()": f"{UNPROVED}db.execute(InAppNotification.__table__.insert().values(link=url))",
    "a model alias assigned in the module": f"N = InAppNotification\n{UNPROVED}db.execute(insert(N).values(link=url))",
    "inline text() with an unproved link": f'{UNPROVED}db.execute(text("{SQL}"), {{"id": 1, "link": url}})',
    "inline text() with parameters in a variable": f'def f(db, params):\n    db.execute(text("{SQL}"), params)',
    "inline text() with a spread dict": f'def f(db, extra):\n    db.execute(text("{SQL}"), {{"id": 1, **extra}})',
    "inline text() without a link parameter": f'def f(db):\n    db.execute(text("{SQL}"), {{"id": 1}})',
    "SQL in a local variable": f'{UNPROVED}q = text("{SQL}")\n    db.execute(q, {{"link": url}})',
    "text().bindparams(link=unproved)": f'{UNPROVED}db.execute(text("{SQL}").bindparams(link=url))',
    "an aliased post_in_app": (
        'from bridge.notifications.in_app import post_in_app as tell\ntell(db, link="https://evil.example")'
    ),
    "an aliased model": 'from bridge.notifications.models import InAppNotification as Row\nRow(link="//evil.example")',
    "a module-qualified post_in_app": (
        'from bridge.notifications import in_app as ia\nia.post_in_app(db, link="//evil.example")'
    ),
    "an aliased caller of a parameter": (
        "def send(db, link):\n    post_in_app(db, link=link)",
        'from bridge.fake import send as s\ns(db, "//evil.example")',
    ),
    "a module-qualified caller of a parameter": (
        "def send(db, link):\n    post_in_app(db, link=link)",
        'import bridge.fake as fake\nfake.send(db, "/dev/x")\nfake.send(db, link="//evil.example")',
    ),
}
GOOD_WRITERS: dict[str, str | tuple[str, str]] = {
    "a literal": 'post_in_app(db, link="/dev/engagements")',
    "an f-string": 'post_in_app(db, link=f"/dev/ideas/{proposal_id}")',
    "no link": "post_in_app(db, link=None)",
    "a template constant": 'T = "/org/inbox?org={org}"\ndef f(db, org):\n    post_in_app(db, link=T.format(org=org))',
    "a parameter's good caller": 'def send(db, link):\n    post_in_app(db, link=link)\nsend(db, "/dev/engagements")',
    "insert(...).values(link=a path)": 'db.execute(insert(InAppNotification).values(user_id=1, link="/dev/x"))',
    "inline text() with a path": f'db.execute(text("{SQL}"), {{"id": 1, "link": f"/dev/ideas/{{pid}}"}})',
    "SQL that writes no link": (
        'db.execute(text("INSERT INTO in_app_notifications (id, user_id, title) VALUES (:a, :b, :c)"), {"a": 1})'
    ),
    "a docstring that mentions the SQL": f'"""{SQL} is what post_in_app runs."""\npost_in_app(db, link=None)',
    "an aliased builder": (
        "from bridge.web_paths import engagement_path as path\npost_in_app(db, link=path(party, engagement_id))"
    ),
    "a module-qualified builder": (
        "from bridge import web_paths\npost_in_app(db, link=web_paths.engagement_path(party, engagement_id))"
    ),
    "an aliased caller of a parameter": (
        "def send(db, link):\n    post_in_app(db, link=link)",
        'from bridge.fake import send as s\ns(db, "/dev/engagements")',
    ),
    "a module-qualified caller of a parameter": (
        "def send(db, link):\n    post_in_app(db, link=link)",
        'import bridge.fake as fake\nfake.send(db, "/dev/x")\nfake.send(db, link="/dev/y")',
    ),
    "an aliased post_in_app": 'from bridge.notifications.in_app import post_in_app as tell\ntell(db, link="/dev/x")',
    "an aliased model": 'from bridge.notifications.models import InAppNotification as Row\nRow(link="/dev/x")',
    "a model alias assigned in the module": 'N = InAppNotification\ndb.execute(insert(N).values(link="/dev/x"))',
    "__table__.insert()": 'db.execute(InAppNotification.__table__.insert().values({"link": "/dev/x"}))',
    "SQL in a local variable": f'def f(db):\n    q = text("{SQL}")\n    db.execute(q, {{"link": "/dev/x"}})',
    "text().bindparams(link=a path)": f'db.execute(text("{SQL}").bindparams(id=1, link="/dev/x"))',
}


def _scan(source: str | tuple[str, str]) -> list[str]:
    """The problems of every writer in ``bridge.fake`` (and ``bridge.other``, which may import from it)."""
    sources = (source,) if isinstance(source, str) else source
    modules = {
        name: Module(name, f"{name.replace('.', '/')}.py", ast.parse(text))
        for name, text in zip(("bridge.fake", "bridge.other"), sources, strict=False)
    }
    sites = writers(modules)
    assert sites  # the scan saw the writer at all
    return [problem for site in sites for problem in problems_of(site, modules)]


@pytest.mark.parametrize("source", BAD_WRITERS.values(), ids=BAD_WRITERS.keys())
def test_the_scan_refuses_a_link_it_cannot_prove(source: str | tuple[str, str]) -> None:
    assert _scan(source)


@pytest.mark.parametrize("source", GOOD_WRITERS.values(), ids=GOOD_WRITERS.keys())
def test_the_scan_accepts_a_proved_link(source: str | tuple[str, str]) -> None:
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
