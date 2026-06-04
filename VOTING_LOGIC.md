# WildePod Voting Consensus

How WildePod decides whether a Category, Species, Activity, or BoundingBox annotation should be considered _valid_, _invalid_, or _uncertain_, and how that decision is computed, persisted, and queried.

## Table of Contents
- [TL;DR](#tldr)
- [Vote weight model](#vote-weight-model)
- [How validity is computed](#how-validity-is-computed)
- [The four validity values](#the-four-validity-values)
- [Where the logic lives](#where-the-logic-lives)
- [Data flow](#data-flow--how-a-vote-becomes-a-stored-validity)
- [BoundingBox cascade](#the-boundingbox-cascade)
- [Querying validity](#querying-validity)
- [What changed in this refactor](#what-changed-in-this-refactor)
- [Migration & backfill](#migration--backfill)
- [Future considerations](#future-considerations)
- [Edge cases worth knowing](#edge-cases-worth-knowing)
- [Where to look in the code](#where-to-look-in-the-code)

---

## TL;DR

Each annotation gets a `validity` field with one of four states. The state is derived from a **weighted vote sum**: normal users count as `1`, staff and expert users count as `5`. Validity is **computed once at save time** (not on every read), and stored on the model so queries are a single field filter.

| Score                  | Validity    |
| ---------------------- | ----------- |
| `score >= 2`           | `VALID`     |
| `-1 <= score <= 1`     | `UNCERTAIN` |
| `score <= -2`          | `INVALID`   |
| (no annotations yet)   | `NULL` (UNSEEN — BoundingBox only) |

A staff or expert vote at vote-time **wins outright** (last-vote-wins) regardless of the surrounding sum.

---

## Vote weight model

| Annotator type                  | Weight |
| ------------------------------- | -----: |
| Normal user (or any bot)        |    `1` |
| Staff user (`is_staff=True`)    |    `5` |
| Expert user (`is_expert=True`)  |    `5` |

The creator of an annotation is always counted in the score — their act of creation _is_ a vote.

**Why 1 and 5, not 1 and 2?**
The wide gap leaves room for a future split (e.g. expert = 3, staff = 5) without redefining the thresholds. The role check (`is_staff or is_expert`) is intentionally decoupled from the numeric weight so a tier-split is a one-line change to `_weight()`.

---

## How validity is computed

For an annotation `obj`:

```
score = weight(obj.created_by)
        + sum(weight(a) for a in obj.accepted_by)
        - sum(weight(a) for a in obj.rejected_by)
```

Then:

| Condition             | Validity     |
| --------------------- | ------------ |
| `score >= 2`          | `VALID`      |
| `score <= -2`         | `INVALID`    |
| otherwise             | `UNCERTAIN`  |

### Concrete examples

| Scenario                                                 | Score | Result      |
| -------------------------------------------------------- | ----: | ----------- |
| Bot creates, no votes                                    |    1  | `UNCERTAIN` |
| Bot creates + 1 normal accept                            |    2  | `VALID`     |
| Bot creates + 1 staff accept                             |    6  | `VALID`     |
| Bot creates + 1 staff reject                             |   -4  | `INVALID`   |
| Bot creates + 2 normal accepts + 1 staff reject          |   -2  | `INVALID`   |
| Staff creates, no other votes                            |    5  | `VALID`     |
| 1 staff accept, 1 staff reject (creator is normal)       |    1  | `UNCERTAIN` |

### Last-staff-vote-wins (vote-time only)

When `vote()` is called and the voter is staff/expert, their decision **immediately** sets validity to `VALID` (accept) or `INVALID` (reject), bypassing the weighted sum. This is how the user gets the experience that "the most recent staff judgment is what stands" — practical because staff conflicts are rare, and the few cases that occur are usually one staff member correcting another.

The plain weighted sum is also used in two other modes (backfill, UI display) — there is no annotator context there, so the override does not apply. That is fine: under the weights chosen (5 vs 1), a single staff vote dominates the sum unless many normals are on the other side, which matches the override's intent.

---

## The four validity values

- **`VALID`** — Consensus reached: the annotation is correct.
- **`INVALID`** — Consensus reached: the annotation is wrong (or rejected).
- **`UNCERTAIN`** — Has been reviewed but votes don't reach a threshold either way.
- **`NULL` = "UNSEEN"** — No reviewer has touched it. Only meaningful for BoundingBox; Category / Species / Activity always have a creator whose vote contributes to a non-null score, so `NULL` only appears as a transitional state (e.g. between migration and backfill).

---

## Where the logic lives

Single source of truth: `siteapps/images/processors/annotation.py`.

```python
@dataclass
class VoteResult:
    validity: str | None    # VALID / INVALID / UNCERTAIN / None
    score: int              # weighted score
    accepted_count: int     # raw count
    rejected_count: int     # raw count
    staff_accept_count: int
    staff_reject_count: int
    staff_override: bool    # True only at vote time when staff/expert decides


def compute_validity(obj, annotator=None, accept=None) -> VoteResult:
    """
    Two modes:
      - vote-time   (annotator + accept given): staff/expert override applies
      - display     (annotator omitted): pure weighted sum
    """
```

`compute_validity()` is the only place the rules are encoded. Everything else reads from it or from the persisted `validity` field.

---

## Data flow — how a vote becomes a stored validity

```
┌──────────────────────────────────────────────────────────────┐
│ HTTP request: user submits an annotation                     │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ vote(obj, annotator, accept)                                 │
│   processors/annotation.py                                   │
│                                                              │
│   Only M2M updates:                                          │
│     obj.accepted_by.add/remove()                             │
│     obj.rejected_by.add/remove()                             │
│   Handles creator-reject edge case (delete or reassign).     │
│   Does NOT compute or write validity.                        │
└──────────────────────────────┬───────────────────────────────┘
                               │
                          (many vote() calls in one request)
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ calculate*AnnotationFlags(image) — end of request            │
│   views/annotation.py                                        │
│                                                              │
│   For each Category / Species / Activity in the image:       │
│       validity = compute_validity(obj).validity              │
│       bulk_update(["validity", "modified"])                  │
│                                                              │
│   For each BoundingBox in the image:                         │
│       validity = cascade_from_children(bbox)                 │
│       bulk_update(["validity", "modified"])                  │
│                                                              │
│   Update image-level flags (has_humans, has_wild_animals,    │
│   *_pipeline_complete, etc.) as before.                      │
└──────────────────────────────────────────────────────────────┘
```

### Why this split?

`vote()` is called multiple times in one request (e.g. accepting a species also implicitly rejects sibling species, votes on the bbox, casts a category vote, etc.). Recomputing validity inside each `vote()` call would mean recomputing the same set of bboxes 5–10 times per submission. Doing it once at the end is correct, atomic, and far cheaper.

`calculate*AnnotationFlags` is the **single writer** for the `validity` field. No other code path touches it. This makes contention impossible and gives a single place to reason about when validity changes.

---

## The BoundingBox cascade

A `BoundingBox` has its own M2M votes (`accepted_by` / `rejected_by`) but `bbox.validity` is **not** computed from them. It is **derived from its children**:

| Children                                | `bbox.validity`         |
| --------------------------------------- | ----------------------- |
| Any child has `validity = VALID`        | `VALID`                 |
| Any child has `validity = UNCERTAIN` or `NULL` | `UNCERTAIN`      |
| All children have `validity = INVALID`  | `INVALID`               |
| No children at all                      | `NULL` (UNSEEN)         |

This means a bbox is considered valid as long as it has _any_ valid categorization (animal / person / vehicle), species, or activity. A bbox with no annotations on it (e.g. after all its categories are rejected) cascades to `UNSEEN`.

The bbox's own M2M votes are still recorded by `vote()` for audit purposes but no longer drive bbox validity directly — children dictate the answer.

---

## Querying validity

After the field is populated, validity queries collapse to simple field filters:

```python
Category.objects.filter(validity="VALID")
Species.objects.valid()             # equivalent — manager helper
Activity.objects.valid_or_uncertain()
image.boundingbox_set.valid()
```

The `BaseAnnotationManager` provides:

- `.valid()`      → `validity = "VALID"`
- `.uncertain()`  → `validity = "UNCERTAIN"`
- `.valid_or_uncertain()` → everything except `INVALID` / `NULL`

These methods work uniformly across all four annotation models because they all share the same `validity` field name.

---

## What changed in this refactor

Before this refactor, three independent implementations of the consensus rule existed:

| Where                                       | Behavior                                                  |
| ------------------------------------------- | --------------------------------------------------------- |
| `BaseAnnotationManager.annotated()`         | Subquery-based, used a binary `is_staff_vote` override    |
| `annotate()` in views (legacy helper)       | Dict-mutating, used `STAFF_OR_EXPERT_VOTE_MULTIPLIER = 2` |
| Export SQL (`siteapps/exports/export_images.sql`) | Weighted sum, staff/expert = 5                            |

These disagreed on edge cases. The ORM-manager version was also outright broken for Category / Species / Activity — it referenced `confidence_threshold` which only exists on BoundingBox, and would `FieldError` whenever called. After the refactor:

- **One function** (`compute_validity`) defines the rule.
- **One writer** (`calculate*AnnotationFlags`) persists `validity` to the DB.
- **Stored on the model** — no per-query recomputation.
- **ORM managers** are simple field filters that work uniformly across all four annotation models.
- The export SQL still recomputes validity on the fly (no schema dependency), but it now uses the same rule and could be replaced with a `WHERE validity = 'VALID'` query once stored values are validated in production.

---

## Migration & backfill

1. **Schema migration** `0056_add_validity_to_annotations.py`
   Adds nullable `validity` CharField to Category / Species / Activity. Extends BoundingBox.validity to allow NULL (UNSEEN).
   Safe to deploy any time — no data writes.

2. **Dry-run report** `python manage.py report_validity_flips`
   Read-only. Iterates all rows and reports the distribution of validity that `compute_validity` would assign. Lets you sanity-check the impact before backfilling.

3. **Backfill** `python manage.py backfill_validity`
   Batched (1000/batch by default), resumable via `--resume-from=<uuid>`, idempotent. Each batch in its own transaction.
   Populates Category / Species / Activity first, then cascades to BoundingBox.

After deploy + backfill, every annotation has a stored `validity`. `calculate*AnnotationFlags` keeps it in sync on every annotation submission.

---

## Future considerations

**Splitting staff vs expert into separate weights** — Anticipated. Only `_weight()` needs to change; the `_is_staff_or_expert()` role check and override logic stay untouched. Past data is _not_ recomputed — the change applies forward only.

**ML pipeline auto-approval** — When megadetector / speciesnet auto-approve high-confidence detections, that will live in a **separate** field (e.g. `ml_approved`), not in `validity`. Keeping the two distinct means consumers can choose: "human-validated only", "ML-approved only", or "either".

**Confidence threshold** — Currently _not_ part of validity. Historically, an ORM filter (`confidence >= confidence_threshold`) silently excluded low-confidence annotations from `valid()`, but a `migrate_images.py` bug was retroactively rewriting `confidence_threshold` on existing bboxes, invalidating ~2k properly human-validated annotations. The refactor removes confidence from the validity pipeline; it's now purely a routing/queue concern (and will tie into the ML pipeline above).

---

## Edge cases worth knowing

- **A bbox can have `validity = VALID` while its child Species has `validity = NULL`.** This is a transient state during deploy/backfill — once backfill runs, child validity is populated and the bbox cascade fires on the next `calculate*AnnotationFlags` invocation.

- **Bbox-level rejections don't directly invalidate the bbox.** Under the new model, only child consensus matters for bbox validity. In practice this rarely diverges from the bbox's own vote pattern, but it's a real semantic change from the previous implementation.

- **Staff vote conflicts** (one staff accepts, another rejects the same annotation) cancel out in the weighted sum. The plan is to use last-staff-vote-wins at write time, but for historical data the resolution is "whatever the weighted sum says" — an acceptable approximation since such conflicts are rare and the M2M tables have no `voted_at` timestamp to do better.

- **The annotation UI** shows raw `accepted_count` / `rejected_count` to all users. Staff and expert users additionally see the weighted score and the computed validity, for debugging and transparency.

---

## Where to look in the code

| Concern                                | File                                                       |
| -------------------------------------- | ---------------------------------------------------------- |
| The rule (`compute_validity`)          | `siteapps/images/processors/annotation.py`                 |
| The M2M-only `vote()` helper           | `siteapps/images/processors/annotation.py`                 |
| Validity field definitions             | `siteapps/images/models/annotation.py`                     |
| `calculate*AnnotationFlags` (the writer) | `siteapps/images/views/annotation.py`                    |
| ORM manager methods                    | `siteapps/images/models/annotation.py` (`BaseAnnotationManager`) |
| Schema migration                       | `siteapps/images/migrations/0056_add_validity_to_annotations.py` |
| Backfill command                       | `siteapps/images/management/commands/backfill_validity.py` |
| Dry-run report                         | `siteapps/images/management/commands/report_validity_flips.py` |
| Test coverage                          | `siteapps/images/tests/test_compute_validity.py`           |
| Export SQL (separate, uses same rule)  | `siteapps/exports/export_images.sql`                       |
