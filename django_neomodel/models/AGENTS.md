# AGENTS.md — `django_neomodel.models`

Abstract `DjangoNode` bases that an application's node classes inherit. Parent context:
[../AGENTS.md](../AGENTS.md) — what counts as generic, and the open-source rule.

## What lives here

| Module | Holds |
| --- | --- |
| `base.py` | `DjangoNeoModelWithCreatedAndUpdatedProps` — `created` and `updated` `DateTimeProperty` stamps (not indexed, not required), both set on every `save()`; abstract (`__abstract_node__`, `Meta.abstract`) |
| `__init__.py` | Re-exports every base: `from django_neomodel.models import DjangoNeoModelWithCreatedAndUpdatedProps` |

## What belongs here

- An abstract node base, or a mixin of properties and relationships for node classes,
  that any Django + neomodel application could use as it stands.
- **Nothing concrete.** Django imports this package whenever `django_neomodel` is in
  `INSTALLED_APPS`, so a concrete `StructuredNode` here would register its label in every
  application.
- No application vocabulary: a base named for one application's concepts belongs in that
  application.

## Conventions

- One base per concern, in a module named for what it is; `__init__.py` re-exports its
  direct children only.
- `__all__` is a `tuple[LiteralString, ...]`.
- Writes that bypass `save()` — raw Cypher bulk upserts — bypass the `created` /
  `updated` stamps too; such a statement sets them itself when they matter.
