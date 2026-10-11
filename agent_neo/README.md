# Agent Neo — graph agent utilities for Django + NeoModel

`agent_neo` ships alongside `django_neomodel` in the same distribution. It provides reusable patterns for agent-oriented graph applications:

- **Analytical product engine** — ensure-on-read for layered computed nodes with design lifecycle
- **Period-rollup graph operations** (`agent_neo.graph_db`) — packaged templates and bulk helpers for period rollup nodes

It builds on the generic Django + NeoModel layer below it: `django_neomodel.models` (the timestamped node base, automatic `created` / `updated` audit fields), `django_neomodel.graph_db` (connection config, query loading, batch execution, cluster retry) and `django_neomodel.util` (Neo4j-safe datetimes, batch-Cypher admin prefetch and search, OpenAPI schemas, JSON-safe values).

## Layering

| Package | Role |
|---------|------|
| `django_neomodel` | Django ↔ NeoModel bridge, generic node bases (`django_neomodel.models`), graph-DB operations (`django_neomodel.graph_db`) and utilities (`django_neomodel.util`) |
| `agent_neo` | Agent graph patterns (analytical product engine, period-rollup graph operations, the `a3` algebra) |
| Your domain app | Concrete node classes, business products, label registration |

## Quick start

```python
from django_neomodel.models import DjangoNeoModelWithCreatedAndUpdatedProps
from django_neomodel.util.neo4j_datetime import apply_neo4j_datetime_coercion_patch
from neomodel import StringProperty

apply_neo4j_datetime_coercion_patch()  # optional; call once at startup if you use zoned datetimes


class EntityType(DjangoNeoModelWithCreatedAndUpdatedProps):
    uri = StringProperty(unique_index=True, required=True)
    label = StringProperty(required=True)
```

```python
from django_neomodel.graph_db import GraphDbConfig, set_label_install_callback
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

- `agent-openapi` — `DjangoNeoModelAutoSchema` in `django_neomodel.util.openapi` for `DjangoField`
- `agent-drf` — reserved for future DRF integrations

## Neo4j datetime patch

`django_neomodel.util.neo4j_datetime.apply_neo4j_datetime_coercion_patch()` is **not** applied on import. Call it explicitly during Django startup if you serialize `zoneinfo` datetimes through Neo4j.
