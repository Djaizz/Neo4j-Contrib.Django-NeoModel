# A3 — Agentic Analytical Algebra

## ADMINISTRATOR'S NOTES

### Status: v1 implemented and law-tested; not yet bound to the interpreter

The algebra exists as code: a hashable coordinate space, a carrier with derived coverage,
two type tags and identity-valued provenance, seven primitive operations closed over
`Carrier | Refuse`, factored operators with an exactness flag and a storage shape, a lattice
slot, three gates, a bridge in both directions, a term language with a shape checker that
decides every refusal before a value is read, and a reference interpreter over an in-memory
store that is `ensure` written from those blocks alone. Thirty-five laws in `laws.py`, each
executable in `tests/agent_neo/a3/` — the lifecycle contracts against the reference
interpreter, which is also the conformance target for any storage binding. Module map, the
decision record and the binding contract: [`SKETCH.md`](SKETCH.md).

Not yet done: binding `agent_neo.analytical_product` to it (a `Resolver`, a `Store`, a
calendar lattice, `Field` declarations on existing products). The shared enums and the key
scheme are bound and tested; the binding contract — what a conformant binding must do, and
the test file it must pass — is stated at the end of `SKETCH.md`.

### Design aspiration

A3 aims for the same *kind* of leverage Codd's relational algebra gave data
systems: a small formal substrate that lets humans and agents innovate at a
**higher abstraction** — composing new analytical structure safely — rather than
rewriting one-off procedures. See
[Historical analogy](#historical-analogy--why-an-algebra).

### Packaging (provisional)

A3 lives inside `agent_neo` for now, which means it ships inside the
`django_neomodel` distribution. That is expedient, not principled: A3 is
storage-agnostic and `django_neomodel` is a Django ↔ Neo4j bridge. The
[Invariants](#invariants-binding-once-code-lands) below make the eventual split a
`git mv` rather than a rewrite — hold that line even when it is inconvenient.

---

## Why this layer exists

A3 is motivated by experience building **agent-authored, agent-evolvable**
analytical layers whose rules were written as prose. Prose governance decays at
agent speed: nothing checks that the documents, the checks and the code still
agree, so they drift apart silently.

> **Governance-by-document is what you do when you cannot govern by construction.
> Prose governance decays at agent speed.**

A3 keeps pushing toward agent-buildable analytics but puts an algebra underneath,
so new structures are composed inside laws instead of imitated from the last
file. Written rules sort into three kinds. Some are **laws** that could execute
and don't. Some are **judgments** that genuinely cannot be derived. And some are
**prohibitions standing in for missing abstractions** — for example, a ban on
hand-editing cached results exists only because identity is not derived, and
canonical file shapes exist because agents author by imitation rather than by
construction.

A3 is the attempt to move the first kind into code, give the second kind a
declared slot, and let the third kind dissolve — so humans and agents can keep
evolving analytical structure without inventing a new vernacular for every
floor.


## Historical analogy — why an *algebra*

Edgar Codd's relational algebra is the inspiration at a **high level**: not
because we need another query language, but because a formal algebra is what
lets people (and now agents) invent at a greater abstraction, more easily. Once
the carrier and operators are closed and lawful, new structure can be composed
inside that space instead of grown as bespoke procedures. SQL and ORMs were
downstream consequences of that floor in the relational world; they are
illustrations of the *leverage*, not the target of this work.

Neo4j already has its data-access surface in Cypher (and ORMs over it). A3 is
not competing with that layer. The missing floor is for **analytical products** —
metrics, rollups, views, lineage, freshness — which otherwise grow as ad-hoc
methods and helpers, and drift. A3's goal is a foundational algebra so humans and agents can
respond to operator needs by composing inside well-understood moves, not by
imitating the last file that looked similar.

The analogy is about *leverage*, not identity:

| Algebraic idea | A3 target |
| --- | --- |
| Uniform carrier | Sparse coordinates over scope × time × classification, with coverage |
| Closed operator set with laws | Restrict, roll, map, and (later) join / compare / rank |
| Equivalences that justify rewriting | Composition laws → property tests and safe reordering |
| Integrity that the algebra respects | Maturity / freshness / invalidation gates; partition side conditions |
| Higher-abstraction invention on top | Domain Concepts / packages authored by humans and agents |

A3 is **not** "SQL for Neo4j," not a Cypher replacement, and not a storage
opinion. It is the bet that analytical flexibility under agent authorship needs
a formal floor at the *product* layer — or governance will keep rotting into
documents.

## What A3 is

**A carrier, a set of operators that compose lawfully over it, and the gates that
decide when a stored answer is still an answer** — for analytical layers whose
author is an agent. Close the moves, publish the laws, and innovation can rise
one abstraction above hand-written rollup code.


Three tiers, with A3 as the new floor:

| Tier | Role | Depends on |
| --- | --- | --- |
| **`a3`** | terms, laws, identity, gates — storage-agnostic | nothing but the stdlib and numeric libs |
| **`agent_neo`** | one *interpreter* of A3 against Neo4j / NeoModel: persistence, cascade, bulk upsert, lineage edges | `a3`, neomodel, Django |
| your domain package | vocabulary, families, policy values, presentation | `agent_neo` |

## The extraction is already latent

This is not a speculative framework. **26 of `agent_neo`'s 37 Python modules
import neither Django nor neomodel** — and the storage-agnostic set is not the
leftovers, it is precisely the conceptual core:

```
identity.py (85)            request.py (108)         freshness.py (53)
enum.py (91)                scope.py (30)            registry.py (38)
metric_projection.py (113)  monthly_rollup_deps.py (70)
populate_progress.py (618)  util/datetime.py (683)
```

~1,900 lines of storage-independent machinery currently sitting inside a graph-DB
package. The eleven modules that *do* bind — `abstract.py`,
`computed_product_cascade.py`, `computed_product_bulk_persist.py`,
`dependency_registry.py`, `period_spine.py`, `graph_db/_core.py` — are the
interpreter.

The first increments took the shared vocabulary and the key scheme; `SKETCH.md` lists what remains to bind.

## What makes it *agentic*

These six properties are what distinguish A3 from "a decent analytics framework,"
and they are why the layer deserves its own name. A formal algebra is what makes
higher-abstraction invention tractable for agents: the moves are closed, the
failures are typed, and conformance is checkable — not a style guide.

1. **Conformance must be machine-checkable, because the author is a machine.** A
   human reads a style guide and applies judgment. An agent needs a checker. Any
   governance rule that cannot execute will drift.

2. **The authority split must be encoded, not stated.** A rule saying which
   packages may change which layers is the most important governance primitive
   an agent-authored system has — and written as a sentence in a markdown file,
   a single import across the boundary breaks it unnoticed. A3 should express
   authority boundaries as something enforceable: import-graph rules, capability
   scopes, CI gates.

3. **Refusal is a first-class result.** Humans muddle through ambiguity; agents
   muddle through it *wrongly*. "This operator does not compose across that
   dimension," "these children do not partition that parent," "no mergeable
   accumulator is stored for this quantity" are more valuable than any number.
   A pattern registry offers lookup — match or miss. An algebra offers a type
   error that says what is missing.

4. **Provenance is the review mechanism, not an audit feature.** Human-written
   analytics are reviewed at code review. Agent-generated analytics are reviewed
   at the answer. Lineage is therefore in the core loop, not the compliance
   annex — and an answer explained as a *term with values substituted in* beats a
   graph walk that recovers only that A depended on B.

5. **Safe evolution is a rate argument.** Mint-new-and-retire rather than mutate
   matters more, not less, when the layer is revised by an agent orders of
   magnitude more often than a human would revise it.

6. **The corpus is the conditioning context.** One canonical form per product
   kind is not a style preference — it is the generator's interface. Structural
   divergence between siblings is ambiguity in the spec the agent is reading.

## Admission test: which rules belong in A3

Sort every candidate rule into one of three buckets. Only two of them get in.

**(a) Laws that should execute → A3 core.**
Three-gate separation (maturity / freshness / invalidation). At most one
`official` instance per logical identity. Layer dependency direction. Retire, do
not mutate. Maximal lineage wiring. Operator composition rules. These are
invariants: property-testable, storage-agnostic, domain-free.

**(b) Judgments that cannot be derived → A3 declares the slot; the project fills it.**
Is 30 minutes the right maturity buffer? What staleness limit does this view
deserve? Which bucket does a given hour belong to? These are real decisions with no correct
default. A3 defines the parameter and **refuses to supply a value**.

**(c) Prohibitions standing in for missing abstractions → keep out.**
If A3 exported one project's prohibitions verbatim, every future consumer would
inherit rules such as a ban on override flags — when the correct end state is not
a prohibition but a derivation, with no surface to override because nothing would
consume one. Ordering rules for folds likewise dissolve into a theorem (see the
operator model).

> Heuristic: **anything phrased as "do not" is a bucket-(c) suspect. Real laws
> read as "is."**

## The operator model (the one genuinely new piece)

A registry of bare callables (`dict[str, Callable]`) carries no algebraic
metadata — an engine built on one cannot tell `sum` from `percentile`, so a
helper that crosses operators with dimensions can emit "the 95th percentile of a
set of 95th percentiles."

A3 operators carry their factorization:

```
lift    : leaf → accumulator
combine : accumulator × accumulator → accumulator   (associative, commutative)
lower   : accumulator → reported value
```

| Operator | lift | combine | lower |
| --- | --- | --- | --- |
| `sum` | `id` | `+` | `id` |
| `average` | `v ↦ (v, 1)` | pairwise `+` | `(s, n) ↦ s/n` |
| `min` / `max` | `id` | `min` / `max` | `id` |
| `percentile` | singleton sketch | sketch merge (t-digest / KLL) | quantile query |
| `proportion` | `v ↦ (active, total)` | pairwise `+` | ratio |

Two consequences worth stating plainly:

- **Averaging averages breaks precisely because callers store `lower(x)` and then
  try to `combine` that.** Quantiles do not decompose at all; the only correct
  constructions are recompute-from-leaves or a mergeable sketch as the payload.
- **Fold order becomes a theorem, not a policy.** If `combine` is a commutative
  monoid, any bracketing of the index set agrees, so the order of folds across
  dimensions stops being a correctness question and becomes a free choice — pick
  the order that maximizes cache reuse. Classification dimensions come along free:
  they are index-set restrictions, and restriction commutes with a monoid fold
  over a partition.

A third consequence is predictive rather than corrective. A linear `map` commutes
with `roll`, so derivatives of the form `qty × rate` can share one
implementation; the same law says which derivatives cannot (anything non-linear
must be computed after the fold), and it surfaces a live side condition: a linear
`qty × rate` map holds **only while the rate is constant over the roll window**.
Time-varying rates break it, and nothing in a registry of bare callables would
notice.

## Shape, as built

```
a3/
  carrier.py    Coordinate (two rollable Dimensions + classifications), Absent
  algebra.py    Carrier (expected · operator tag · lowered_from · provenance as identities · gaps · family)
                lift roll restrict rekey map join lower | slice shift classify scale diff | rank | plan_roll
                every primitive absorbs a Refuse
  operators.py  Operator = lift/combine/lower + exact + partial_ok + value_type + columns/encode/decode;
                Sum Min Max (exact) Count Mean WeightedMean Proportion Percentile; OperatorRegistry (runs the laws)
  lattice.py    Lattice (up/down, multi-valued), MappingLattice
  product.py    Layer LifecycleStatus · Concept (family, opaque revision, Field roles + columns, term or declared
                dependencies) · Identity + KeyScheme (canonical) · Instance + LineageRef · Ask · Refuse · servable
  gates.py      maturity | freshness | lineage → gate() → GateOutcome
  bridge.py     Resolver, Store; carrier_from_instances, instances_from_carrier (canonical, columns, role ⇔ tag)
  term.py       Ensure(Ask | AskFrom) Lift Roll Restrict Slice Classify Shift Rekey Map Join Lower · Env · shape ·
                evaluate · leaves · leaf_ask
  ops.py        Ensure Retire Invalidate — the contracts only a store can fulfil
  reference.py  MemoryStore + ReferenceInterpreter — those contracts fulfilled from the blocks; the conformance target
  laws.py       35 laws with hypotheses, each naming the block it forces
```

What was *removed* on the way, because no law forced it: a stored per-child coverage mask
(coverage is derived from `expected` and the lattice); an `Identity` duplicating the
coordinate's fields; an empty `Accumulator` marker; an operator `unit` (the empty fold is
`Absent`); a `commutative` flag (commutativity is a precondition of every operator, since a
fold runs over an unordered set); `Scale`, `Diff`, `Rank`, `Warm`, `Compose`, `Project`, `Explain` as
primitives or contracts (the first three expand into `map`/`join`; a warm-up is a loop, a
composition a `join`, the serving boundary a one-line `servable`, provenance a lookup on the
carrier); a `Gate` protocol (three functions); four refuse reasons nothing produced; a
duplicated lifecycle enum; `relift` and Gray's `AggregateKind` (one existed only for the
other — `exact` is the property actually consulted, and it is checkable); `classify` as a
primitive (it is `rekey` with a computed classification); a carrier-relative "known keys" rule
in the roll denominator (the denominator is intrinsic: lattice and classifier alone); a dead
`double_counted` coverage state (a non-partition lattice refuses under every policy);
`Concept.key` (the revision is the store's recipe key, opaque).

What was *added*, because a law demanded it: the operator tag and `lowered_from` with the
re-entry rule (`LAW_TAG_GUARDS_FOLD`, `LAW_REPORTED_REENTRY`: a report re-enters only an
operator not in its history or exact in it — mean of means unconstructible, mean of daily
totals writable); `Field` roles and columns on `Concept` so the bridge knows what a stored
payload *is* and can rebuild a stored `(average, count)` as a mean (`LAW_BRIDGE_ROUND_TRIP`);
`restrict` and `rekey` ("working hours only", period-over-period, peer-vs-peer); classifiers
bound to the roll so the denominator is intrinsic and slicing commutes with rolling; `on_missing`
with a `PARTIAL` policy gated by `partial_ok`; identity-valued provenance and finest-known gaps
(`LAW_PROVENANCE_IS_LEAVES`, `LAW_ROLL_PATH_INDEPENDENT`); a term language and a value-free
`shape` so WHAT/HOW separation is real (`LAW_SHAPE_SOUND`), with relative leaves so a recipe
serves a family; `LineageRef`s so the lineage gate decides from facts the store already
holds; derived-or-declared `depends_on` and `check_layers`, which finally give
`Layer.may_depend_on` a consumer inside the algebra; a `Refuse` that every primitive absorbs
(`LAW_REFUSE_ABSORBS`); a reference interpreter that makes the lifecycle laws executable and
shows the blocks suffice to write `ensure` (`LAW_ENSURE_RECURSIVE`).

## Scope boundaries — where A3 stops

A3 covers the derivation stack from source observations up through metrics, and
the derivation of views from metrics. It stops at three walls, on purpose:

- **Judgment is not algebraic.** "That value looks off" is a threshold policy —
  scope-configured, occasionally political, changeable without any underlying
  fact changing. It can be modelled as a morphism to a label lattice, but there
  are no useful rewrite laws, so there is nothing to optimize. That is the honest
  boundary, not a gap.
- **Presentation is a different formalism.** Charts, tables, tabs, row/column
  semantics belong to a grammar of graphics. Unifying it with an aggregation
  algebra would be a category error.
- **Domain vocabulary stays in the domain.** Scope-local time, a maturity buffer,
  classification dimensions (e.g. weekday vs weekend, in-window vs
  out-of-window), and a
  multi-level scope lattice are domain concerns. Their *shapes* generalize —
  a domain-local time basis, a maturity lag parameter per granularity,
  classification dimensions as part of identity, a scope lattice with partition
  side conditions. Parametrize those; never hard-code the values.

One boundary is a feature rather than a limitation. Real scope hierarchies are
often not lattices: not every parent has a clean child partition. So `roll` over
scope carries a **partition side condition**: aggregating to a parent is
meaningful only if the children partition it, with no gaps and no
double-counting. A3 should make coverage a first-class, propagated property.
Summing whatever children are found turns coverage gaps into silent
undercounts.

## Invariants (binding, and tested)

- **`a3` imports only the standard library and itself**, and `import agent_neo.a3` succeeds
  with Django, neomodel and the Neo4j driver masked — `test_import_boundary.py`. The
  package's own `__init__` resolves its Django-bound names lazily for this reason.
- Every operator declares `kind` and `partial_ok` and satisfies `lift`/`combine`/`lower`; a
  holistic operator with no accumulator cannot be registered — `OperatorRegistry`.
- Every law in `laws.py` has an executable test, or says it is an interpreter contract.
- A3 declares policy **slots** (`max_staleness`, `maturity_lag`, `Env.now`, classifiers,
  lattices) and ships no policy **values**.
- A3 contains no project's requirements corpus and no domain vocabulary; the public leak
  guard covers it.
- Lifecycle vocabulary is exactly `official` / `provisional` / `retired`, defined once here
  and re-exported by the interpreter.
- `shape(t) is Refuse ⟺ evaluate(t) is Refuse`, with the same reason: every refusal is
  decidable without a payload.

## Do not

- Do not add a governance module that has no runner. Governance that only
  documents is worse than none once it carries an import path — it looks official
  while it rots.
- Do not import any one project's requirements corpus into `a3`. Those belong to
  the consuming project; only their executable form belongs here.
- Do not let a bucket-(c) prohibition in because it is currently true. Fix the
  abstraction or leave it in the domain.
- Do not generalize beyond what a second consumer has actually demanded. Until
  one exists, a framework shaped by a single use comes out shaped like that use.
  Extract only what has been shown to be domain-free; let the rest wait.
- Do not let `a3` acquire a storage opinion. The moment it does, it stops being
  the floor and becomes a second `agent_neo`.

## Open questions

1. **Instances: versioned per slot, or refreshed in place?** `LAW_RETIRE_NOT_MUTATE` is the
   contract; the interpreter's unique `cache_key` index makes a recompute a `MERGE` in place.
   A data-model decision for the interpreter, recorded in `SKETCH.md`.
2. **Concept as term, everywhere.** `Concept.term` is optional and `depends_on` is derived
   from it when present. Whether every product's recipe should be a term — making recipes
   diffable and invalidation sub-term-precise — is decided by binding the first real family.
3. **Packaging.** `a3` inside `agent_neo` ships an algebra inside a Django/Neo4j
   distribution. The import boundary is the hedge; revisit when a second consumer appears.
4. **Rolling a classification to `all`.** Classifications are sliced and used as keys; a
   fold *over* a classification (day + night = all) would be a third rollable dimension with
   its own lattice. Not needed by any law yet; deferred until a term needs it.

## Related

- `agent_neo/README.md` — the current package layering.
- `agent_neo/analytical_product/` — machinery A3 would lift and reinterpret.
