# A3 playground sketch

Status: **candidate stubs**, not a shipped engine. Names and contracts are the
deliverable. Bodies raise or return placeholders. Nothing here imports
Neo4j, Django, or `agent_neo.graph_db`.

Charter: [`AGENTS.md`](AGENTS.md).

---

## CRUD / Cypher vs product algebra

SQL and Cypher already encode data-manipulation algebras for **records and
graphs**: create, match, update, delete, project, join at the store level.
Agents building analytical layers do not struggle inventing those.

They struggle inventing **product-level moves** every time a new metric,
rollup, view, or refuse rule appears:

- materialize by logical identity (ensure-on-read / populate warm)
- fold across space or time with typed aggregators (so p95-of-p95 is unconstructible)
- qty×rate maps, day/hour slices, join-to-table, period compare, rank
- invalidate by lineage, gate on maturity/freshness, retire-not-mutate
- return a typed **Refuse** when composition is illegal

A3 closes that higher set. It is not another query language.

---

## Layers in this sketch

| Module | Holds |
| --- | --- |
| `carrier.py` | `Coordinate`, `Coverage`, `Carrier`, `Absent` |
| `operators.py` | `Operator` = lift / combine / lower; built-ins |
| `product.py` | `Concept`, `Ask`, `Identity`, `Instance`, `Refuse` |
| `ops.py` | High-level op Protocols (Ensure, Roll, Gate, …) |
| `laws.py` | Property-test *intent* for composition |

```
Ask ──Ensure/Warm──► Instance
                        │
         Roll / Map / Slice / Join / Diff / Rank
                        │
                    Project ──► View-shaped payload
                        │
                   Compose (may stay ephemeral)

Invalidate / Gate / Retire / Explain cut across the above.
```

---

## Op catalog (kernel)

| Op | Intent |
| --- | --- |
| **Ensure** | Idempotent materialize-by-Ask: probe → gates → compute → persist → retire prior |
| **Warm** | Bulk Ensure over mature windows / subject sets (populate) |
| **Roll** | Fold a Carrier along one dimension with an `Operator`; requires partition coverage |
| **Map** / **Scale** | Pointwise or qty×rate transform; Scale is linear only while rate is constant on the window |
| **Slice** | Restrict by classification dims (day/hour/…); commutes with monoid Roll |
| **Join** | Align products on subject/period keys → row Carrier |
| **Diff** | Compare to baseline or peer window |
| **Rank** | Order rows by score |
| **Project** | Metric Instance → View payload (serving boundary) |
| **Compose** | Multi-product answer graph; may not persist |
| **Invalidate** | Mark needs-redo / cascade; **no force-redo knob** |
| **Gate** | Policy stop → `Refuse` (immature, stale, authority, …) |
| **Retire** | Mint-new; flip prior to retired (no in-place mutate) |
| **Explain** | Structured provenance trail (not a Cypher walk) |

**Domain-pack slot (not kernel):** `Interpret` — threshold/status rules over
Metrics. Facility NLP and Present/markdown stay out of A3.

---

## Laws (sketch)

- Under a commutative-monoid `combine`, `Roll` along independent dimensions
  commutes: `roll(d₁, roll(d₂, c)) == roll(d₂, roll(d₁, c))`.
- `Slice` is an index-set restriction; it commutes with monoid `Roll` over a
  partition of that set.
- `Roll` to a parent is legal only if children’s `Coverage` partitions the
  parent (no gaps, no double-count).
- Storing `lower(x)` then calling `combine` is illegal; combine works on
  accumulators only.
- `Percentile` without a mergeable sketch → `Refuse(NoMergeableAccumulator)`.

See `laws.py` for property-test intent strings.

---

## Non-goals

- Replacing Cypher / NeoModel persistence
- Shipping policy *values* (maturity minutes, operating hours) — only slots
- Importing any one project’s requirements corpus
- Full term language for Concepts (open question in the charter)
- Wiring these stubs into `analytical_product` in this commit

---

## Relation to `analytical_product`

The unfinished construction site already has a strong **interpreter** shape
(Request → Identity → get/serve → three gates → cascade). This sketch names the
**algebra** that interpreter should eventually obey so agents compose inside
laws instead of cloning the last MetricSet file.
