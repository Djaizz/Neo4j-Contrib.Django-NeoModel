# AGENTS.md — `django_neomodel`

Orientation for coding agents working in this package: what it is, where generic
Django + NeoModel code goes, and a survey of every affordance it implements, with why
Django needs each one.

---

## What this package is

The bridge between Django and neomodel. `DjangoNode` makes a neomodel `StructuredNode`
look enough like a Django model for the admin, forms, Django REST framework and
drf-spectacular; `DjangoNeoModelAdmin` runs the admin over `NodeSet`s; `NeomodelConfig`
feeds neomodel its settings from Django's. Beside the bridge, three subpackages hold the
generic code applications build on.

| Path | What lives there |
| --- | --- |
| `__init__.py` | `DjangoNode`, `DjangoField`, `NeoManager`, and the `NodeSet` patches the admin needs (`query`, `totally_ordered`) |
| `admin.py` | `DjangoNeoModelAdmin`, `NeoModelChangeList`, and the neomodel `Q`-parsing patch |
| `apps.py` | `NeomodelConfig` |
| `management/commands/` | `install_labels`, `clear_neo4j` |
| `models/` | Abstract node bases — see [models/AGENTS.md](models/AGENTS.md) |
| `graph_db/` | Graph-database operations: connection config and lifecycle, Cypher loading, retried and batched execution, template binding — see [graph_db/AGENTS.md](graph_db/AGENTS.md) |
| `util/` | Generic utilities, one concern per module — see [util/AGENTS.md](util/AGENTS.md) |

`agent_neo`, shipped in the same distribution, builds on this package.

## Where generic code goes

- **Generic** means it deals only with Django, neomodel, the Neo4j driver and their
  optional integrations (Django REST framework, drf-spectacular): no application concept,
  no domain vocabulary. Code that knows an application's concepts stays in that
  application.
- **A node base class goes in `models/`; an operation on the graph database
  (connecting, loading or executing Cypher) in `graph_db/`; anything else in `util/`**, in
  a module named for its one concern.
- **This package imports nothing from `agent_neo` or from any application.** The layering
  runs one way: applications → `agent_neo` → `django_neomodel` → neomodel.
- **This is public, open-source code.** No customer, product, site or project names,
  identifiers or design-document citations, in code, comments, docstrings, tests, data or
  commit messages. Examples use neutral vocabulary (books, shelves, libraries).
- `tests/agent_neo/test_no_domain_leaks.py` guards this tree with `agent_neo`'s: a
  private denylist kept outside the repository (skipped, with the reason, when absent),
  design-citation shapes, dangling `.md` and private-name pointers, and each package's
  import boundary — the one that keeps `agent_neo` out of this package.
- An optional dependency is imported only by the module that needs it (type-only imports
  under `TYPE_CHECKING`), so importing the package never requires it.

## Tests

- `tests/django_neomodel/` — unit tests of the generic layer (`models/`, `graph_db/`,
  `util/`); no Neo4j server needed.
- `tests/someapp/` — the integration tests, against a live Neo4j: CI starts one with
  `scripts/docker-neo4j.sh`, then runs `tests/manage.py install_labels` and `migrate`
  before `pytest`.
- `pyproject.toml` points pytest at `tests.settings`.

---

## Affordance survey

### Module: `__init__.py`

#### 1. `DjangoField`
- **Purpose**: Wraps a neomodel `Property` in the Django `Field` API.
- **Justification**: Django Admin, forms and DRF expect Django `Field` objects with
  attributes like `name`, `attname`, `verbose_name`, `help_text`, `blank`, `choices`, and
  methods like `formfield()` and `has_default()`. A neomodel `Property` has none of them.
- **Key attributes**:
  - `empty_values = [None, '']` — Django's `display_for_field()` reads `field.empty_values`
  - `remote_field = None` — DRF reads it on every field
- **Key methods**: `formfield()` (the Django form field), `save_form_data()`,
  `value_from_object()`, `get_choices()`, `to_python()`
- **Necessity**: ✅ **Required** for Django Admin, forms and DRF.

#### 2. `Query` dataclass and its per-`NodeSet` descriptor
- **Purpose**: Gives every `NodeSet` its own Django-style `query` (`select_related=False`,
  `order_by=[]`).
- **Justification**: Django's `ChangeList.get_ordering` reads `queryset.query.order_by`,
  and `DjangoNeoModelAdmin.get_queryset` writes the translated ordering there. A
  descriptor, not a class attribute, so `NodeSet`s never share one `Query`; the default
  `order_by` is empty so no stray `pk` ordering leaks in.
- **Necessity**: ✅ **Required** (Django's changelist reads it).

#### 3. `NodeSet.totally_ordered`
- **Purpose**: Every `NodeSet` reports its ordering as not total (`False`), unless
  neomodel's `NodeSet` ever answers for itself.
- **Justification**: Django 6.1's `ChangeList.get_ordering` asks
  `queryset.order_by(*ordering).totally_ordered` before appending its `-pk` tiebreak; a
  `NodeSet` lacked the attribute, so every changelist raised `AttributeError`. "Not total"
  is Django 6.0's answer for these models (they report no unique field): the changelist
  appends `-pk`, which `DjangoNeoModelAdmin` translates to the primary-key property.
- **Necessity**: ✅ **Required** under Django 6.1 and later.

#### 4. `_ObjectsDescriptor`
- **Purpose**: Django-like `Model.objects`, returning `Model.nodes` (a `NodeSet`).
- **Justification**: Django Admin and Django code expect an `.objects` manager; neomodel
  uses `.nodes`.
- **Necessity**: ✅ **Required** for Django Admin compatibility.

#### 5. `NeoManager`
- **Purpose**: A Django-style manager whose `get_queryset()` returns a `NodeSet`.
- **Justification**: Django Admin reads a model's default manager and calls its
  `get_queryset()`.
- **Necessity**: ✅ **Required**.

#### 6. `MetaClass`
- **Purpose**: Extends neomodel's `NodeMeta` to set a `NeoManager` as each `DjangoNode`
  subclass's default manager, at class creation.
- **Justification**: The manager must exist before Django Admin first reads it.
- **Necessity**: ✅ **Required**.

#### 7. `DjangoNode`
The base class for neomodel nodes with Django integration.

- **`objects`** — the `_ObjectsDescriptor` above. ✅ Required.
- **`_meta`** (a `classproperty`) — builds Django `Options` from the node's properties
  (one `DjangoField` each), sets `concrete_model` to the class (drf-spectacular reads it),
  and installs a `pk` property returning the primary-key value — a `property` subclass
  carrying `.name`, which the admin reads. `unique_together` raises
  `NotImplementedError`. ✅ Required: Django Admin introspects `Model._meta`.
- **`full_clean()`** — validates through neomodel's deflation and raises Django
  `ValidationError`s. ✅ Required: Django forms call it before saving.
- **`validate_unique()`** — checks unique-indexed properties against existing nodes.
  ✅ Required: Django forms call it.
- **`validate_constraints()`** — a no-op (no Django ORM constraints exist here).
  ✅ Required: Django Admin's `ModelForm` calls it.
- **Django signals** — `pre_save()`, `post_save()`, `pre_delete()`, `post_delete()` send
  Django's signals while the `NEOMODEL_SIGNALS` setting is true (the default).
  ✅ Required when Django apps listen for model lifecycle signals.
- **`serializable_value()`** — returns `None` for `attr=None` (Django Admin sometimes
  passes it, which would otherwise raise `TypeError`), else the attribute as a string.
  ✅ Required by Django Admin.

#### 8. `classproperty`
- **Purpose**: A class-level property, for `_meta`.
- **Necessity**: ✅ **Required** by the `_meta` implementation.

---

### Module: `admin.py`

#### 1. The `Q`-filters parsing patch
- **What**: `QueryBuilder._parse_q_filters` is replaced on module import (see
  **Key intercepts** below for why).
- **Necessity**: ✅ **Required** while neomodel's parser mis-detects nested `Q` objects.

#### 2. `NeoModelChangeList`
- **`get_queryset()`** — for a `NodeSet` root: applies the list filters, then the search
  on the clean root, then the ordering; it skips Django's `filter(<Django Q>)` and
  `apply_select_related`, both of which corrupt or break a `NodeSet`.
- **`get_results()`** — replaces `result_list` with the paginator's page: a `NodeSet`'s
  `_clone()` may drop its filters, so iterating it could list every node while the
  paginator counts only the filtered ones.
- **Necessity**: ✅ **Required** for search and filters on `NodeSet` changelists.

#### 3. `DjangoNeoModelAdmin`
The base `ModelAdmin` for neomodel nodes. Unlike the `DjangoNode` integrations (reactive —
Django calls or reads them), these are proactive overrides of Django Admin's defaults;
whether each is necessary depends on whether the incompatibility it works around could be
fixed lower down (for instance by making `NodeSet` meet Django Admin's expectations).

- **Option defaults** — no foreign-key or many-to-many options (neomodel has neither);
  `date_hierarchy = None`, because `DjangoField` has no `get_internal_type()`.
- **Permission methods** — `has_add_permission()`, `has_view_permission()`,
  `has_change_permission()`, `has_view_or_change_permission()`,
  `has_delete_permission()` all allow. Required for the admin to display pages, since
  neomodel nodes are not wired into Django's auth system. ⚠️ Could the admin work without
  them if they were?
- **`get_ordering()`** — translates `pk` / `-pk` to the primary-key property (neomodel's
  query builder rejects `pk`); orders by the primary key when nothing else is given, and
  returns no ordering when the model has no primary key. ✅ Required.
- **`get_search_results()`** — Django Admin's search semantics with neomodel `Q`: the
  term is split with `smart_split` (quoted phrases stay one term), every term must match
  at least one `search_fields` entry (OR across fields, AND across terms), and the
  `^` / `=` / `@` prefixes select `istartswith` / `iexact` / `search` (default
  `icontains`). No distinct is needed. ✅ Required: Django's default builds Django ORM
  `Q` objects.
- **`get_queryset()`** — returns `model.objects` (a `NodeSet`; `objects.all()` would be a
  list), wraps its `order_by()` so `pk` is translated even when the admin orders later
  (and carries the wrapper onto the `NodeSet`s `order_by()` returns), applies
  `get_ordering()`, keeps `query.order_by` in step, makes sure `q_filters` is a `Q`, and
  finally re-translates any `pk` left in `order_by_elements`. ✅ Required.
- **`get_changelist()`** — returns `NeoModelChangeList` (inside an error-logging
  wrapper). ✅ Required for the class it returns.
- **`changelist_view()`**, **`changeform_view()`** — error-logging wrappers;
  `changelist_view()` answers an HTML error page under `DEBUG`. ⚠️ Debugging helpers.
- **`get_readonly_fields()`**, **`get_form()`** — keep neomodel's internal
  `element_id` / `element_id_property` out of admin forms.
- There is no `get_object()` override: Django's default reads `queryset.model`, which
  neomodel's `NodeSet` provides, and the primary-key field from `_meta`.

---

### Module: `apps.py`

#### `NeomodelConfig`
- **Purpose**: The AppConfig; `ready()` copies `NEOMODEL_NEO4J_BOLT_URL`,
  `NEOMODEL_FORCE_TIMEZONE` and `NEOMODEL_MAX_CONNECTION_POOL_SIZE` from Django's
  settings into neomodel's `config` (neomodel 7 warns that these legacy attributes are
  deprecated in favour of its `get_config()` API).
- **Necessity**: ✅ **Required** for neomodel to take its configuration from Django.

---

### Module: `management/commands/`

- **`install_labels`** — wraps `neomodel.install_all_labels()`. ⚠️ Convenience.
- **`clear_neo4j`** — wraps `neomodel.clear_neo4j_database()`. ⚠️ Convenience.

---

## Summary

### Core requirements (reactive to Django's API, or required by the admin pipeline)
1. ✅ `DjangoField`, including `empty_values` and `remote_field`
2. ✅ `DjangoNode` with `_meta`, `full_clean()`, `validate_unique()`,
   `validate_constraints()`, `serializable_value()` and the signal hooks
3. ✅ `_ObjectsDescriptor` / `.objects`, `NeoManager`, `MetaClass`
4. ✅ The per-`NodeSet` `query` (Django's changelist reads `query.order_by`) and the
   `NodeSet.totally_ordered` answer (Django 6.1's changelist asks it)
5. ✅ `NeomodelConfig`
6. ✅ `DjangoNeoModelAdmin.get_ordering()`, `get_queryset()`, `get_search_results()` and
   `get_changelist()`, with `NeoModelChangeList`
7. ✅ The `Q`-filters parsing patch

### Needs validation (proactive overrides that may be unnecessary)
1. ⚠️ `DjangoNeoModelAdmin`'s permission methods — could Django Admin work without them if
   neomodel nodes were integrated with Django's auth system?

### Potentially removable (debugging and convenience)
1. ⚠️ The error-logging wrappers in `get_changelist()`, `changelist_view()` and
   `changeform_view()`
2. ⚠️ The management commands

---

## Key intercepts

### Primary key (`pk`) translation
- **Problem**: Django Admin orders by `pk`, but neomodel knows no property named `pk`; its
  query builder validates property names when it builds the query and raises
  `ValueError` on `pk`.
- **Solution**, in layers:
  1. `get_ordering()` translates `pk` to the primary-key property when the admin asks
     for the ordering.
  2. `get_queryset()` applies that ordering and wraps the `NodeSet`'s `order_by()` to
     translate any later `pk`, carrying the wrapper onto the `NodeSet`s it returns.
  3. A final pass cleans `order_by_elements` of any `pk` that slipped through.
- **Why necessary**: Django Admin may apply ordering after `get_queryset()` returns, so
  the translation has to sit at the `order_by()` level too.

### `NodeSet`, not a list
- **Problem**: `model.objects.all()` returns a `list`, but Django Admin's changelist and
  paginator need a queryset-like object (`count()`, `order_by()`, …).
- **Solution**: use `model.objects` itself, which is a `NodeSet` (via
  `_ObjectsDescriptor`).

### The `query` descriptor
- **Problem**: patched as a class attribute, one `Query` object — with a default
  `order_by` of `["pk"]` — was shared by every `NodeSet`.
- **Solution**: a descriptor returning a per-instance `Query`, with an empty default
  `order_by`, so no default `pk` ordering interferes with the translation.

### The changelist pipeline
- **Problem**: Django's `ChangeList.get_queryset()` filters with a Django `Q` and calls
  `apply_select_related` before the search runs, corrupting a `NodeSet`; its
  `get_results()` iterates a `_clone()` that may have lost the filters.
- **Solution**: `NeoModelChangeList` searches on the clean root, orders afterwards, skips
  both Django ORM steps, and lists the paginator's page.

### `Q`-filters parsing (monkey-patch)
- **Problem**: neomodel's `_parse_q_filters` checks `isinstance(child, QBase)` and, for
  `Q` objects nested as children of `q_filters`, gets `False` — so it subscripts the `Q`
  as a tuple (`child[0]`, `child[1]`) and fails with `"'Q' object is not
  subscriptable"`. Nesting happens whenever `filter()` wraps the existing filters
  (`self.q_filters = Q(self.q_filters & Q(...))`) or `Q` objects are combined with `&`.
- **Root cause**: the `isinstance` check does not recognize those `Q` objects even though
  `Q` subclasses `QBase` — possibly an import or class-hierarchy issue, or how wrapped `Q`
  objects are created.
- **Solution**: `QueryBuilder._parse_q_filters` is replaced, on module import, with a
  version that:
  1. detects a `Q` by `isinstance(child, QBase)`, `isinstance(child, Q)`, or the type
     name;
  2. treats a child that cannot be subscripted but has `children` and `connector` as a
     `Q`;
  3. recurses through the patched method, so every nesting level is handled.
- **Note**: a workaround for a neomodel bug; the fix belongs in neomodel.

---

## Questions to validate

1. Can the error handling in `get_changelist()`, `changelist_view()` and
   `changeform_view()` be simplified or removed?
2. Are the management commands used, or do users call neomodel's functions directly?
3. Could `DjangoNeoModelAdmin`'s overrides be eliminated by fixing the incompatibilities
   at the `NodeSet` / `DjangoNode` level instead?
