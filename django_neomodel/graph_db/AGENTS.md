# AGENTS.md — `django_neomodel.graph_db`

Graph-database operations for Django + neomodel applications: connecting, loading Cypher
from files, executing it under cluster retry and in bounded batches, and binding template
placeholders. Parent context: [../AGENTS.md](../AGENTS.md) — what counts as generic, and
the open-source rule.

## What lives here

| Module | Holds |
| --- | --- |
| `_core.py` | The implementation. `GraphDbConfig` — connection settings as literal values (a caller whose configuration names them indirectly, through environment variables or otherwise, resolves them first); `build_neomodel_database_url()`; `connect_db()`, idempotent within a process, retried through leader elections, and optionally installing labels and indexes through the callback registered with `set_label_install_callback`, behind a precheck that skips `install_all_labels` when every index and constraint it would create already exists. `reconnect_neo4j_driver`, `is_graph_db_connected`, `reconnect_graph_db_if_needed`, `connect_graph_db`. `retry_neo4j_cluster_operation` and `is_transient_neo4j_error`, tuned by the `NEO4J_CLUSTER_LEADER_SWITCH_*` globals, read at call time. `GraphDbQueryAndReturnHeaderList` and `load_query` — a `.cypher` file and the columns its last RETURN yields, comments stripped first. `batched_cypher_execute` — one `UNWIND $rows` statement per chunk, chunks bounded by items and by rows (`GRAPH_DB_BATCH_SIZE`) |
| `config.py`, `connection.py`, `queries.py`, `retry.py`, `batch.py` | `_core.py`'s names by topic; `batch.py` adds `neo4j_bulk_timestamps`, the `created` / `updated` pair a raw Cypher write sets to match `DjangoNeoModelWithCreatedAndUpdatedProps.save()` |
| `execute.py` | `cypher_read` / `cypher_write` — one statement under cluster retry; `for_each_chunk`; `DEFAULT_IN_CHUNK_SIZE` / `DEFAULT_DELETE_CHUNK_SIZE`; `safe_connect_relationship` — a neomodel `.connect()` under cluster retry, re-raising cardinality violations |
| `query_bind.py` | `bind_label`, `bind_label_and_property`, `bind_where_clause` — the `__LABEL__`, `__PROPERTY__` and `__WHERE__` placeholders of packaged templates; labels and property names come from model classes, never from user input |
| `cypher_templates.py`, `cypher/` | `load_query_text` (a statement read whole, RETURN or not) and the packaged `COUNT_NODES_BY_PROPERTY_IN_KEYS` / `DELETE_NODES_BY_PROPERTY_IN_KEYS` |
| `__init__.py` | Re-exports the public names above |

## Environment

Read by `_core.py`, each with its default:

| Variable | Default | Effect |
| --- | --- | --- |
| `AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS` | `5` | Attempts before a transient error is re-raised |
| `AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS` | `30.0` | Delay before the first retry |
| `AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER` | `2.0` | Growth of the delay per retry |
| `AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS` | `120.0` | Ceiling of the delay |
| `AGENT_NEO_QUIET_NEO4J_INSTALL` | on | Silences `install_all_labels` output (`0` / `false` / `no` / `off` shows it) |
| `AGENT_NEO_LABEL_INSTALL_PRECHECK` | on | The label-install precheck (`0` / `false` / `no` / `off` always runs the full install) |

## Conventions

- Query text lives in `.cypher` files, loaded once at import; a template is bound through
  `query_bind`, never assembled from request data.
- Writes run under `retry_neo4j_cluster_operation` with `reconnect_neo4j_driver` as the
  reconnect, so a leader election costs a wait, not a failure.
- Nothing connects at import; `GraphDbConfig.connect_db()` is the way in.
- A statement that carries an application's or an analysis's meaning stays with the code
  that owns that meaning — `agent_neo.graph_db` keeps the analytical period-rollup
  templates and bulk helpers, which build on this package.
- Tests: `tests/django_neomodel/test_graph_db_*.py`.
