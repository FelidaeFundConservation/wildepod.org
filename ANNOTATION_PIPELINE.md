# WildePod Annotation Pipeline

How a volunteer's tag submission becomes votes, how those votes become a stored `validity`, and how `validity` gates the Category/Species/Activity pipeline-complete flags. Complements [`VOTING_LOGIC.md`](https://github.com/FelidaeFundConservation/wildepod.org/blob/main/VOTING_LOGIC.md), which documents the consensus rule in more detail — this doc covers the full request-to-database flow around it (bbox lifecycle, batch tagging, auto-approval).

Links below are permalinked to commit [`cb367b40`](https://github.com/FelidaeFundConservation/wildepod.org/commit/cb367b4042c491994501da6461fdc9f02881cad2) on branch [`fix/orphaned-bbox-rejection-blocks-pipeline`](https://github.com/FelidaeFundConservation/wildepod.org/tree/fix/orphaned-bbox-rejection-blocks-pipeline) (PR [#569](https://github.com/FelidaeFundConservation/wildepod.org/pull/569)).

## 1. Data model

Four annotation types, all sharing the same shape:

```
BoundingBox  (image, x, y, w, h, created_by, accepted_by M2M, rejected_by M2M, validity)
 ├── Category   (bounding_box FK, name: animal/vehicle/person/unannotated, created_by, accepted_by, rejected_by, validity)
 ├── Species    (bounding_box FK, name: FK→SpeciesName,               created_by, accepted_by, rejected_by, validity)
 └── Activity   (bounding_box FK, name: FK→ActivityType,              created_by, accepted_by, rejected_by, validity)
```

- [`Validity` enum](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/models/annotation.py#L135-L138) — `VALID` / `INVALID` / `UNCERTAIN`. `NULL` on the field means "UNSEEN" — only meaningful for `BoundingBox`, since Category/Species/Activity always have a creator vote.
- [`BoundingBox`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/models/annotation.py#L147-L209)
- [`Category`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/models/annotation.py#L268-L313)
- [`Species`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/models/annotation.py#L318-L389)
- [`Activity`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/models/annotation.py#L413-L460)

## 2. Vote weights and `compute_validity()`

The weight model, score formula, and validity thresholds are the consensus rule proper — see [`VOTING_LOGIC.md`](./VOTING_LOGIC.md#vote-weight-model) for those (`compute_validity()`, [`processors/annotation.py:104-172`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L104-L172), is the single place that rule is encoded). This doc picks up from there: how a submission produces the votes `compute_validity()` consumes, and how the resulting `validity` gates the pipeline-complete flags.

## 3. `vote()` — the M2M-only mutator

[`processors/annotation.py:203-235`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L203-L235)

```python
def vote(obj, annotator, accept):
    if accept:
        obj.accepted_by.add(annotator); obj.rejected_by.remove(annotator)
    else:
        obj.accepted_by.remove(annotator); obj.rejected_by.add(annotator)
        if obj.created_by == annotator:            # self-reject edge case
            if obj.accepted_by.count() == 0:
                obj.delete(); return               # no other support -> gone
            other = obj.accepted_by.first()
            obj.created_by = other; obj.accepted_by.remove(other); obj.save()  # reassign creator
```

Never touches `validity` — that's owned exclusively by the flag-calculation pass (§5). Any one-off caller (scripts, tests) must call `calculate*AnnotationFlags(image)` afterward.

[`reject_children()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L238-L257) wraps `vote()` to reject-vote a list of Category/Species/Activity rows from a list of annotators, stopping on a child once it's self-deleted so it doesn't operate on a dangling pk.

## 4. Request flow: turning a submission into votes

Entry point: [`annotation_processor()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1355), hit by [`SpeciesAnnotationProcessorView`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1551) / [`ActivityAnnotationProcessorView`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1556) POST. Parses the request, then calls `process_species_annotations` / `process_activity_annotations` → [`process_annotations()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L769-L826) → [`handle_changes()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L526-L561), which runs three phases against `initial_bboxes` (what existed before) vs `formatted_annotations` (what's in this submission):

```
handle_bbox_deletions()   bbox in initial but not in submission → delete (if creator/staff) or reject_children (§3)
handle_bbox_additions()   bbox in submission but not in initial → create_bbox() (+ its first Category/Species/Activity)
handle_bbox_updates()     bbox in both → edit_bbox_coordinates(), then process_species()/process_activity()
```

- [`handle_bbox_deletions()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L361-L404)
- [`handle_bbox_additions()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L346-L358) / [`create_bbox()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L316-L343)
- [`edit_bbox_coordinates()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L407-L445) — small coordinate drift (<2% on all of x/y/w/h) or staff/creator → edit in place. Bigger drift from a non-creator → reject-vote the old box, spawn a brand-new one via `create_bbox()`.
- [`handle_bbox_updates()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L448-L495)
- [`process_species()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L609-L634) / [`process_activity()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L637-L657) — get-or-create the tag for this bbox, accept-vote it if not the caller's own, reject-vote every *other* sibling tag on the same bbox (so switching your species pick effectively demotes your old pick). `process_species` also calls [`infer_category()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L593-L606) → [`handle_inference()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L565-L589) to derive/accept the Category (person/animal/vehicle/unknown) from the species group, and reject-votes conflicting Category rows.

Special path: [`auto_approve_single_human()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L714-L765) — a single high-confidence `person` bbox gets an automated expert-weight accept vote from a dedicated bot annotator ([`get_automation_annotator()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L660-L711)), instantly completing the category pipeline; species is set complete directly since there's no wildlife to identify.

## 5. The single writer: `calculate*AnnotationFlags`

Called once at the [end of every request](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1466-L1474), never anywhere else:

```
calculateCategoryAnnotationFlags(image)
calculateSpeciesAnnotationFlags(image)
calculateActivityAnnotationFlags(image)
image.save()
```

Each does the same three-step dance for its model (Category/Species/Activity):

1. [`annotate()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1632-L1671) — calls `compute_validity()` per row, stashes `status`/`score`/counts into a display dict. Pure computation, no writes.
2. [`_save_annotation_validity()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1674-L1689) — `bulk_update`s `validity` from that dict. This *is* the write.
3. [`_recompute_bbox_validity_for_image()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1692-L1724) — cascades every bbox's `validity` from its children only (not from the bbox's own `accepted_by`/`rejected_by`, per `VOTING_LOGIC.md`'s "Edge cases worth knowing"): any child `VALID` → `VALID`; any `UNCERTAIN`/`NULL` → `UNCERTAIN`; all `INVALID` → `INVALID`; no children → `NULL` (UNSEEN).

Then each function applies its own gate to decide the corresponding `*_pipeline_complete` flag:

| | [Category](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1728-L1830) | [Species](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1834-L1919) | [Activity](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/views/annotation.py#L1923-L1990) |
|---|---|---|---|
| gate | no `UNCERTAIN` category or bbox, ≥1 non-`INVALID` bbox, `image.processed` | no `UNCERTAIN` species, ≥1 `VALID` species, ≥2 checkers or staff vote, `image.processed`, **`category_pipeline_complete`** | no `UNCERTAIN` activity, ≥1 `VALID` activity, has wild animals or humans, ≥2 checkers or staff vote, `image.processed` |
| sets | `has_humans/animals/vehicles`, `category_pipeline_complete` | `has_wild_animals`, `has_cats`, `species_pipeline_complete` | `activity_pipeline_complete` |

This chained dependency (`species` needs `category` complete first) is exactly why one dead bbox with an orphaned, never-voted `UNCERTAIN` category could permanently stall the whole image — the bug fixed in PR [#569](https://github.com/FelidaeFundConservation/wildepod.org/pull/569).

## 6. Batch tagging

[`tag_batch()`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/processors/annotation.py#L499-L522) applies the same species/activity tag to every `VALID`/`UNCERTAIN` bbox across a set of "burst" images at once, reusing `process_species`/`process_activity`.

## Summary

The recurring pattern: **mutate M2M state via `vote()`/`reject_children()` during the request → recompute+persist `validity` once at the end via `compute_validity()` (never anywhere else) → cascade bbox validity from children → gate the pipeline-complete flags.**

## Related

- [`VOTING_LOGIC.md`](https://github.com/FelidaeFundConservation/wildepod.org/blob/main/VOTING_LOGIC.md) — the consensus rule in depth, plus migration/backfill history
- [`backfill_orphaned_bbox_rejections`](https://github.com/FelidaeFundConservation/wildepod.org/blob/cb367b4042c491994501da6461fdc9f02881cad2/siteapps/images/management/commands/backfill_orphaned_bbox_rejections.py) — one-off sweep for images stuck under the pre-fix behavior
- PR [#569](https://github.com/FelidaeFundConservation/wildepod.org/pull/569) — the fix and its tests
- Issue [#570](https://github.com/FelidaeFundConservation/wildepod.org/issues/570) — unrelated pre-existing flaky test noticed while validating #569's CI
