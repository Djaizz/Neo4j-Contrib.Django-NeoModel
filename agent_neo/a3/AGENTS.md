# A3 — Agentic Analytical Algebra

## ADMINISTRATOR'S NOTES

### Status: charter, not yet implementation

This document records **why this layer should exist and what belongs in it**. No
A3 code has been written yet. Everything under "Intended shape" is intent, not
inventory — verify against the directory before relying on any module named here.

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

The reference implementation A3 is factored from is a production analytical layer
**authored and evolved by an agent** under a written governance harness: 32
requirement files (30 administrator-verified, 2 draft), eleven design elements
with a necessity/sufficiency proof, a health assessment, and a divergence
register. It is unusually well-specified work.

It still drifted, within weeks:

- the necessity/sufficiency proof covers 28 requirements; there are 32
- the problem-pattern coherence check links to a health assessment file that no
  longer exists
- three `…MetricSet`-suffixed facades still accept a `force_redo` argument that a
  verified requirement prohibits — and silently discard it (one does `del force_redo`)
- a spatial-temporal rollup helper mechanically generates the full operator cross
  product — 121 field rules including `qty_p95OverSpace_p95OverTime` and
  `qty_avgOverSpace_avgOverTime`, neither of which denotes anything

None of that is carelessness. It is evidence about the medium:

> **Governance-by-document is what you do when you cannot govern by construction.
> Prose governance decays at agent speed.**

Look at the requirements through that lens and they sort into three kinds. Some
are **laws** that could execute and don't. Some are **judgments** that genuinely
cannot be derived. And some are **prohibitions standing in for missing
abstractions** — `ANALYTICAL-NO-FORCE-REDO-ARGS` forbids a knob because
invalidation cannot be computed; the mandated two-phase rollup order is policy
because the operator laws are unstated; `ANALYTICAL-CODE-GEN`'s canonical forms
and six named anti-patterns exist because agents author by imitation rather than
by construction.

A3 is the attempt to move the first kind into code, give the second kind a
declared slot, and let the third kind dissolve — by putting an algebra under
the fast-evolving analytical structures operators and agents keep asking for.

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
metrics, rollups, views, lineage, freshness — which today grow as Python
methods, prompt-shaped requirements, and ad-hoc helpers, and then drift for the
reasons above. A3's goal is a foundational algebra so humans and agents can
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

A3's first increment is therefore mostly **naming a split that already exists**,
not inventing one. The same move was already run one level down when domain
vocabulary was extracted out of `agent_neo` into its domain package.

## What makes it *agentic*

These six properties are what distinguish A3 from "a decent analytics framework,"
and they are why the layer deserves its own name. A formal algebra is what makes
higher-abstraction invention tractable for agents: the moves are closed, the
failures are typed, and conformance is checkable — not a style guide.

1. **Conformance must be machine-checkable, because the author is a machine.** A
   human reads a style guide and applies judgment. An agent needs a checker. Any
   governance rule that cannot execute will drift.

2. **The authority split must be encoded, not stated.** "Domain packages may
   evolve analytical vocabulary; the platform retains control of structural and
   ingestion layers" is the most important governance primitive in the harness
   — and it is currently a sentence in a markdown file. It was already violated
   (a structural module importing a private analytical one). A3 should express
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
deserve? What counts as a working hour? These are real decisions with no correct
default. A3 defines the parameter and **refuses to supply a value**.

**(c) Prohibitions standing in for missing abstractions → keep out.**
If A3 exports today's harness verbatim, every future consumer inherits a rule
forbidding `force_redo` — when the correct end state is not a prohibition but a
derivation, with no surface to force because nothing would consume one. Likewise
the mandated rollup order, which should dissolve into a theorem.

> Heuristic: **anything phrased as "do not" is a bucket-(c) suspect. Real laws
> read as "is."**

## The operator model (the one genuinely new piece)

Today's operator registry is `dict[str, Callable]` with no algebraic metadata —
the engine cannot tell `sum` from `percentile`. That is why the cross-product
helper can emit "the 95th percentile of a set of 95th percentiles."

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
  monoid, any bracketing of the index set agrees, so spatial-then-temporal
  ordering stops being a correctness mandate and becomes a free choice — pick the
  order that maximizes cache reuse. Classification dimensions come along free:
  they are index-set restrictions, and restriction commutes with a monoid fold
  over a partition.

A third consequence is predictive rather than corrective. A linear `map` commutes
with `roll`, which is *why* several quantity×rate derivatives could be unified
into one class — discovered empirically in the reference implementation, but
the same law says which derivatives cannot unify that way (anything non-linear
must be computed after the fold), and it surfaces a live side condition: a
linear `qty × rate` map holds **only while the rate is constant over the roll
window**. Time-varying rates break it, and nothing in a registry of bare
callables would notice.

## Intended shape (not yet built)

```
a3/
  algebra/      quantity + accumulator types, operator registry with laws,
                composition typecheck
  carrier/      the coordinate space: scope lattice, time lattice,
                classification dimensions, coverage
  product/      Concept (design node) vs Computed Instance (run-time node),
                identity, lifecycle vocabulary
  gates/        maturity | freshness | invalidation — three separable gates
  lineage/      dependency model, cascade semantics (mark-then-lazy-recompute)
  governance/   authority boundaries + conformance runner
```

Increment order, smallest decisive first:

1. **Name the split that already exists** — move the 26 storage-agnostic modules
   in. Near-zero risk; it is a rename of something already true.
2. **Add the accumulator to the operator model** — the one genuinely new piece,
   and the one that makes ill-typed rollups unconstructible rather than merely
   regrettable.
3. **Ship the three-gate model as the headline abstraction** — maturity /
   freshness / invalidation as three separately-testable gates is the most
   transferable idea in the source harness, and most systems conflate the latter
   two.
4. **A conformance runner, not a requirements corpus** — the generic asset is
   "requirements execute and are checked in CI," never the specific requirements.

Deliberately deferred: `join`, `compare`, `rank`, and anything resembling a term
language. Those need the carrier settled first (see Open questions).

## Scope boundaries — where A3 stops

A3 covers the derivation stack from source observations up through metrics, and
the derivation of views from metrics. It stops at three walls, on purpose:

- **Judgment is not algebraic.** "That reading looks off" is a threshold policy —
  scope-configured, occasionally political, changeable without any underlying
  fact changing. It can be modelled as a morphism to a label lattice, but there
  are no useful rewrite laws, so there is nothing to optimize. The reference
  implementation reflects this: **many MetricSet classes against few judgment
  facades.** That asymmetry is the honest boundary, not a gap.
- **Presentation is a different formalism.** Charts, tables, tabs, row/column
  semantics belong to a grammar of graphics. Unifying it with an aggregation
  algebra would be a category error.
- **Domain vocabulary stays in the domain.** Scope-local time, a maturity buffer,
  classification dimensions (weekday vs weekend, operating vs idle), and a
  multi-level scope lattice are domain concerns. Their *shapes* generalize —
  a domain-local time basis, a maturity lag parameter per granularity,
  classification dimensions as part of identity, a scope lattice with partition
  side conditions. Parametrize those; never hard-code the values.

One boundary is a feature rather than a limitation. Real scope hierarchies are
not lattices — the source domain's own draft requirement concedes that not every
parent has a clean child partition. So `roll` over scope carries a **partition
side condition**: aggregating to a parent is meaningful only if the children
partition it, with no gaps and no double-counting. A3 should make coverage a
first-class, propagated property. Current practice sums whatever children were
found, which is exactly how coverage gaps become silent undercounts.

## Invariants (binding once code lands)

- **`a3` imports nothing from `neomodel`, `django`, or `agent_neo.graph_db`.**
  Enforce it with an import-boundary test, not a convention. This is what keeps
  the eventual package split cheap.
- Every operator declares its accumulator type and its `(lift, combine, lower)`
  factorization. An operator without one cannot be registered.
- Composition laws ship as **property tests over generated carriers**, not as
  prose — e.g. `roll(d₁, roll(d₂, c)) == roll(d₂, roll(d₁, c))` for independent
  dimensions under a commutative-monoid `combine`.
- A3 declares policy **slots** and never ships policy **values**.
- A3 contains no domain requirement corpus. It contains the runner that checks
  one.
- Lifecycle vocabulary is exactly `official` / `provisional` / `retired`. No
  fourth state, no supersession edge.

## Do not

- Do not add a governance module that has no runner. Governance that only
  documents is worse than none once it carries an import path — it looks official
  while it rots.
- Do not import the source project's 32 requirements into `a3`. They belong to
  the consuming project; only their executable form belongs here.
- Do not let a bucket-(c) prohibition in because it is currently true. Fix the
  abstraction or leave it in the domain.
- Do not generalize beyond what a second consumer has actually demanded. This
  layer is being factored from **n = 1**, and frameworks factored from one example
  come out shaped like that example. Extract what the de-domaining exercise
  already proved generic; let the rest wait.
- Do not let `a3` acquire a storage opinion. The moment it does, it stops being
  the floor and becomes a second `agent_neo`.

## Open questions

1. **The carrier — and this is load-bearing.** The working model is a sparse,
   typed, multi-dimensional array over lattice-valued dimensions, with a coverage
   mask. Whether that mask is part of the *value*, part of the *coordinate*, or a
   third thing determines whether `join` is well-behaved at all. Settle this
   before any binary operator is designed.
2. **Packaging.** `a3` inside `agent_neo` ships an algebra inside a Django/Neo4j
   distribution, which works against the goal of reuse beyond one project. Revisit
   when a second consumer appears; until then the import boundary is the hedge.
3. **Concept as recipe vs Concept as term.** The source design already has the
   right node — a design-level Concept holding "meaning, compute logic, declared
   dependencies" — but it currently holds a Python method pointer. If it held the
   term instead, dependency edges would derive from free variables rather than
   hand declaration, Concepts would become diffable, invalidation could narrow to
   affected subterms, and explanation would be term pretty-printing. That is the
   whole distance between the current system and an algebraic one. Not yet a
   commitment.
4. **Operator set beyond folds.** Every operator in the source engine is a fold
   along one dimension. The observed demand is full of `join`, `compare`
   (period-over-period, peer-vs-peer) and `rank` — currently thousands of lines of
   hand-written composition code that does not know it is a join. Blocked on (1).

## Related

- `agent_neo/README.md` — the current package layering.
- `agent_neo/analytical_product/` — the interpreter A3 would be factored out from.
- The reference implementation — a production, agent-authored analytical layer
  built on `agent_neo`, and so far the only consumer. Its governance harness
  (requirements corpus, necessity/sufficiency design proof, health assessment) is
  the source material this charter generalizes from. It is not public; the
  observations quoted above are reproduced here without identifying detail
  because they are evidence about the *medium*, not about that project.
