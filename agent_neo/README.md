# Agent Neo — graph agent utilities for Django + NeoModel

`agent_neo` ships alongside `django_neomodel` in the same distribution. It provides reusable patterns for agent-oriented graph applications:

- **Timestamped NeoModel base** — automatic `created` / `updated` audit fields
- **Admin prefetch** — batch Cypher to avoid N+1 in Django Admin and DRF list views
- **Graph DB helpers** — connection config, query loading, batch execution, cluster retry
- **Analytical product engine** — ensure-on-read for layered computed nodes with design lifecycle

## Layering

| Package | Role |
|---------|------|
| `django_neomodel` | Low-level Django ↔ NeoModel bridge |
| `agent_neo` | Agent graph patterns (bases, prefetch, graph helpers, analytical product engine) |
| Your domain app | Concrete node classes, business products, label registration |

## Quick start

```python
from agent_neo.util.django_neomodel.models import DjangoNeoModelWithCreatedAndUpdatedProps, apply_neo4j_datetime_coercion_patch
from neomodel import StringProperty

apply_neo4j_datetime_coercion_patch()  # optional; call once at startup if you use zoned datetimes


class EntityType(DjangoNeoModelWithCreatedAndUpdatedProps):
    uri = StringProperty(unique_index=True, required=True)
    label = StringProperty(required=True)
```

```python
from agent_neo.graph_db import GraphDbConfig, set_label_install_callback
from neomodel.sync_.database import db


def install_my_labels() -> None:
    import myapp.models  # noqa: F401 — register StructuredNode labels
    db.install_all_labels()


set_label_install_callback(install_my_labels)

config = GraphDbConfig(uri="bolt://localhost:7687", username="neo4j", password="secret", database="neo4j")
config.connect_db(install_labels_and_indexes=True)
```

## Analytical product nodes

Define layered computed nodes with declarative dependency registries:

```python
from agent_neo.analytical_product import (
    AbstractAnalyticalComputedProduct,
    ComputedNodeLayer,
    AnalyticalProductRequest,
    register_computed_node_class,
)

class RelatedItemMetricSet(AbstractAnalyticalComputedProduct):
    LAYER = ComputedNodeLayer.METRIC
    DEPENDS_ON_RELS = (...)
    # implement _compute(scope, identity, request)

register_computed_node_class(RelatedItemMetricSet)
```

Use `AnalyticalProductRequest` with `scope_name` (your tenant/scope identifier) rather than domain-specific names.

## Optional extras

```bash
pip install django_neomodel[agent-openapi,agent-drf]
```

- `agent-openapi` — `DjangoNeoModelAutoSchema` in `agent_neo.util.django_neomodel.models` for `DjangoField`
- `agent-drf` — reserved for future DRF integrations

## Neo4j datetime patch

`apply_neo4j_datetime_coercion_patch()` is **not** applied on import. Call it explicitly during Django startup if you serialize `zoneinfo` datetimes through Neo4j.
