# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db.models import Count, Q, Sum
from images.models import (
    Activity,
    ActivityType,
    Annotator,
    Bot,
    BoundingBox,
    Category,
    Image,
    Species,
    SpeciesName,
    Upload,
)
from images.models.annotation import Validity

# TODO: This entire module is very hacky and needs to be refactored
MAX_VOTES_PER_IMAGE = 2
VOTE_THRESHOLD = 1

OBJECT_ANNOTATION_TYPE = "OBJECT"
SPECIES_ANNOTATION_TYPE = "SPECIES"
ACTIVITY_ANNOTATION_TYPE = "ACTIVITY"

UNKNOWN_CATEGORY = "unknown"

PERSON_CATEGORY = "person"
ANIMAL_CATEGORY = "animal"
VEHICLE_CATEGORY = "vehicle"

# The automation criterion applied to single high-confidence human images, and the identity
# of the dedicated automation bot whose accept vote auto-completes them. This is a distinct
# Bot from the detection MegaDetector so that ordinary detection votes keep normal (weight 1)
# authority while only the automation annotator carries expert-equivalent (weight 5) authority.
SINGLE_HUMAN_RULE = "single_human"
AUTOMATION_BOT_NAME = "MegaDetector-Auto"
AUTOMATION_BOT_VERSION = "v5a.0.0"

# Vote weight model: normal=1, staff/expert=5, threshold>=2 for VALID, <=-2 for INVALID.
# Future tier splits (expert vs staff) only require updating _weight() — the
# _is_staff_or_expert() role check stays as the override gate.
NORMAL_VOTE_WEIGHT = 1
STAFF_OR_EXPERT_VOTE_WEIGHT = 5
VALIDITY_THRESHOLD = 2


@dataclass
class VoteResult:
    """
    Result of computing validity for a Category, Species, or Activity annotation.

    `validity` is one of "VALID" / "INVALID" / "UNCERTAIN" (never None for these
    models since they always have a creator whose vote contributes to the score).
    Consumers use the count fields for UI display; vote() uses validity to
    persist.

    Fields:
    - validity: VALID / INVALID / UNCERTAIN
    - score: weighted score (creator + accepts - rejects, with staff=5 / normal=1)
    - accepted_count / rejected_count: raw vote counts from M2M tables (unweighted)
    - staff_accept_count / staff_reject_count: subset of the above from staff/expert
    - staff_override: True if validity was decided by a staff/expert overriding
      via last-vote-wins (set only when called from vote() at vote time)
    """

    validity: Optional[str]
    score: int
    accepted_count: int
    rejected_count: int
    staff_accept_count: int
    staff_reject_count: int
    staff_override: bool


def _is_staff_or_expert(annotator: Optional[Annotator]) -> bool:
    """Override-authority check — kept independent of vote weight so future tier splits don't break it.

    True for staff/expert human annotators and for automation bot annotators (those carrying an
    ``automation_criteria``). A criteria-bearing automation annotator's vote therefore wins outright
    (last-vote-wins) and carries expert-equivalent weight, so a single automated accept completes the
    annotation the same way an expert human's would.
    """
    if not annotator:
        return False
    if annotator.human and (annotator.human.is_staff or annotator.human.is_expert):
        return True
    return bool(annotator.automation_criteria)


def _weight(annotator: Optional[Annotator]) -> int:
    return STAFF_OR_EXPERT_VOTE_WEIGHT if _is_staff_or_expert(annotator) else NORMAL_VOTE_WEIGHT


def compute_validity(
    obj,
    annotator: Optional[Annotator] = None,
    accept: Optional[bool] = None,
) -> VoteResult:
    """
    Compute validity for a Category, Species, or Activity annotation.

    Two modes:
    - With annotator+accept (called at vote time): if the voter is staff/expert,
      their decision wins outright (last-staff-vote-wins). Otherwise falls
      through to the weighted sum.
    - Without annotator (backfill / display): pure weighted sum from current
      M2M state.

    Always returns one of VALID/INVALID/UNCERTAIN. NULL/UNSEEN is reserved for
    BoundingBox.validity (set by the cascade in calculate*AnnotationFlags when
    a bbox has no annotations).
    """
    # Use .all() (not select_related) so we benefit from any prefetch_related
    # the caller set up. For non-prefetched callers (like vote()), Django
    # falls back to a query as before. Backfill / report commands set up
    # Prefetch(... queryset=Annotator.objects.select_related("human")) so
    # .human access is free here.
    accepted = list(obj.accepted_by.all())
    rejected = list(obj.rejected_by.all())
    accepted_count = len(accepted)
    rejected_count = len(rejected)
    staff_accept_count = sum(1 for a in accepted if _is_staff_or_expert(a))
    staff_reject_count = sum(1 for a in rejected if _is_staff_or_expert(a))

    # Last staff/expert vote wins outright when called from vote()
    if _is_staff_or_expert(annotator):
        if accept:
            validity = Validity.VALID
            score = _weight(annotator)
        else:
            validity = Validity.INVALID
            score = -_weight(annotator)
        return VoteResult(
            validity,
            score,
            accepted_count,
            rejected_count,
            staff_accept_count,
            staff_reject_count,
            staff_override=True,
        )

    # Weighted sum (creator's vote always counts)
    score = _weight(obj.created_by)
    score += sum(_weight(a) for a in accepted)
    score -= sum(_weight(a) for a in rejected)

    if score >= VALIDITY_THRESHOLD:
        validity = Validity.VALID
    elif score <= -VALIDITY_THRESHOLD:
        validity = Validity.INVALID
    else:
        validity = Validity.UNCERTAIN
    return VoteResult(
        validity,
        score,
        accepted_count,
        rejected_count,
        staff_accept_count,
        staff_reject_count,
        staff_override=False,
    )


def flatten_annotorious_annotations(annotations: list) -> dict:
    """Function to take an annotorious formatted list and flatten it with numerical bounding boxes"""
    logging.info("Flattening annotorious annotations..")
    formatted_annotations = {}
    for annotation in annotations:
        # Annotorious created ids add a # in front of the annotation id. Remove it
        clean_uuid = annotation["id"].replace("#", "")

        # Get the x,y,w,h values from the annotation
        # Annotorious values are in percent so divide by 100 to conform with Mega Detectors values
        [x, y, w, h] = [
            round(float(point), 6) / 100 for point in annotation["target"]["selector"]["value"].split(":")[1].split(",")
        ]

        # Append the annotation to the list
        formatted_annotations[clean_uuid] = {
            "id": clean_uuid,
            "category": annotation["body"][0]["value"] if "value" in annotation["body"][0] else None,
            "confidence": annotation["body"][0]["confidence"] if "confidence" in annotation["body"][0] else None,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        }
    logging.info("Successfully flattened annotorious annotations..")
    return formatted_annotations


def vote(obj, annotator: Annotator, accept: bool):
    """
    Cast a vote for an annotation object (BoundingBox, Category, Species, Activity).

    Updates the M2M tables only. Validity is computed and persisted by
    calculate*AnnotationFlags later in the request cycle — DO NOT touch
    obj.validity here. This keeps a single writer for the field and avoids
    contention between vote() and the cascade.

    Edge case: if the creator rejects their own annotation with no other
    accepts, the object is deleted. If there are other accepters, creation
    is reassigned to one of them and obj.save() persists that change.

    Callers outside the standard annotation_processor flow (one-off scripts,
    test fixtures) must invoke calculate*AnnotationFlags(image) after their
    vote() calls to keep validity fields in sync.
    """
    if accept:
        obj.accepted_by.add(annotator)
        obj.rejected_by.remove(annotator)
    else:
        obj.accepted_by.remove(annotator)
        obj.rejected_by.add(annotator)

        # Undo creation if the creator is reannotating their own work
        if obj.created_by == annotator:
            if obj.accepted_by.count() == 0:
                obj.delete()
                return
            other_annotator = obj.accepted_by.first()
            obj.created_by = other_annotator
            obj.accepted_by.remove(other_annotator)
            obj.save()  # persist created_by reassignment


def set_image_checked_by(annotation_type, image, annotator):
    """Add an annotator to the annotation checked_by"""
    # Set image to "checked" by the annotator
    if annotation_type == SPECIES_ANNOTATION_TYPE:
        image.species_checked_by.add(annotator)
    elif annotation_type == ACTIVITY_ANNOTATION_TYPE:
        image.activity_checked_by.add(annotator)


def set_image_skipped_by(annotation_type, image, annotator):
    """Add an annotator to the annotation skipped_by"""
    # Set image to "skipped" by the annotator
    if annotation_type == SPECIES_ANNOTATION_TYPE:
        image.species_skipped_by.add(annotator)
    elif annotation_type == ACTIVITY_ANNOTATION_TYPE:
        image.activity_skipped_by.add(annotator)


def create_category(annotation_dict: Dict[str, Any], bbox_obj: BoundingBox, annotator: Annotator):
    """Function to create a category object from an annotation dictionary"""
    # Create the category object
    _ = Category.objects.create(
        bounding_box=bbox_obj,
        name=annotation_dict["category"],
        created_by=annotator,
        confidence=annotation_dict["confidence"],
    )
    return


def create_species(annotation_dict: Dict[str, Any], bbox_obj: BoundingBox, annotator: Annotator):
    """Function to create a species object from an annotation dictionary"""
    # Create the species object
    _ = Species.objects.create(
        bounding_box=bbox_obj,
        name=SpeciesName.objects.get(name=annotation_dict["category"]),
        created_by=annotator,
        confidence=annotation_dict["confidence"],
    )

    return


def create_activity(annotation_dict: Dict[str, Any], bbox_obj: BoundingBox, annotator: Annotator):
    """Function to create an activity object from an annotation dictionary"""
    # Create the activity object
    _ = Activity.objects.create(
        bounding_box=bbox_obj,
        name=ActivityType.objects.get(name=annotation_dict["category"]),
        created_by=annotator,
        confidence=annotation_dict["confidence"],
    )

    return


def create_bbox(annotation_type: str, annotation_dict: Dict[str, Any], image_obj: Image, annotator: Annotator):
    """Function to create a bounding box object from an annotation dictionary"""
    bbox_obj = BoundingBox.objects.create(
        image=image_obj,
        x=annotation_dict["x"],
        y=annotation_dict["y"],
        w=annotation_dict["w"],
        h=annotation_dict["h"],
        confidence=annotation_dict["confidence"],
        created_by=annotator,
    )

    # Create the annotation object for the bbox as well
    if annotation_type == OBJECT_ANNOTATION_TYPE:
        create_category(annotation_dict, bbox_obj, annotator)
    elif annotation_type == SPECIES_ANNOTATION_TYPE:
        create_species(annotation_dict, bbox_obj, annotator)

        logging.info("New bounding box created in Species stage.")

        # Based on species_group field, set the category if possible.
        # If not, set category as 'unknown.'
        infer_category(species_name=annotation_dict["category"], bbox_obj=bbox_obj, annotator=annotator)

    elif annotation_type == ACTIVITY_ANNOTATION_TYPE:
        create_activity(annotation_dict, bbox_obj, annotator)

    return bbox_obj


def handle_bbox_additions(annotation_type, initial_bboxes, formatted_annotations, image, annotator):
    # Next, handles all additions
    for bbox_id in formatted_annotations:
        # If the annotation is not in the initial list, it is a new annotation
        if bbox_id not in initial_bboxes:
            # Create the bounding box
            create_bbox(
                annotation_type=annotation_type,
                annotation_dict=formatted_annotations[bbox_id],
                image_obj=image,
                annotator=annotator,
            )
    logging.info("Successfully created all new bounding boxes")


def handle_bbox_deletions(initial_bboxes, formatted_annotations, user, annotator, image):
    for bbox_id in initial_bboxes:
        if bbox_id not in formatted_annotations:
            try:
                # First get the bounding box
                bbox_obj = BoundingBox.objects.get(id=bbox_id)
                # If the annotator is the same as the current user or if it is an expert/staff user, then the object can be deleted
                if (
                    user.is_staff or user.is_expert or bbox_obj.created_by == annotator
                ) and bbox_obj.created_by.human is not None:
                    # Then delete it
                    bbox_obj.delete()
                    logging.info(f"Deleting bounding box with id {bbox_id}.")
                else:
                    # vote() updates M2M only; bbox.validity is owned by
                    # calculate*AnnotationFlags which runs later in the request.
                    vote(bbox_obj, annotator, accept=False)
                    logging.info(f"Rejected bounding box with id {bbox_id}. Object still exists in rejected state.")
            except ObjectDoesNotExist:
                logging.info(f"Bounding box with id {bbox_id} doesn't exist in image {image.id}. Skipping deletion.")

    logging.info("Successfully removed all deleted bounding boxes")


def edit_bbox_coordinates(user, bbox_obj, formatted_annotations, annotator, image):
    bbox_id = str(bbox_obj.id)

    new_x = formatted_annotations[bbox_id]["x"]
    new_y = formatted_annotations[bbox_id]["y"]
    new_w = formatted_annotations[bbox_id]["w"]
    new_h = formatted_annotations[bbox_id]["h"]

    # If the user is expert/staff or original annotator, we directly edit the bounding box
    if (
        user.is_staff
        or user.is_expert
        or bbox_obj.created_by == annotator
        or all(
            [
                abs(bbox_obj.x - new_x) < 0.02,
                abs(bbox_obj.y - new_y) < 0.02,
                abs(bbox_obj.w - new_w) < 0.02,
                abs(bbox_obj.h - new_h) < 0.02,
            ]
        )
    ):
        bbox_obj.x = new_x
        bbox_obj.y = new_y
        bbox_obj.w = new_w
        bbox_obj.h = new_h
        bbox_obj.save()
    else:
        # Original bounding box was modified significantly by the annotator. Cast a reject vote on the original.
        vote(bbox_obj, annotator, accept=False)
        # Create a new bounding box
        bbox_obj = create_bbox(
            annotation_type=OBJECT_ANNOTATION_TYPE,
            annotation_dict=formatted_annotations[bbox_id],
            image_obj=image,
            annotator=annotator,
        )

    return bbox_obj


def handle_bbox_updates(
    annotation_type, initial_bboxes, formatted_annotations, image, user, annotator, batch_tag_images
):
    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        if bbox_id in formatted_annotations:
            # Get the initial bounding box & category object
            try:
                bbox_obj = BoundingBox.objects.get(id=bbox_id)
                # Edit bbox if changes made, create separate object is change is large
                bbox_obj = edit_bbox_coordinates(
                    user=user,
                    bbox_obj=bbox_obj,
                    formatted_annotations=formatted_annotations,
                    annotator=annotator,
                    image=image,
                )
            except ObjectDoesNotExist:
                logging.info(f"Bounding box with id {bbox_id} doesn't exist. Skipping update.'")
                continue

            if annotation_type == SPECIES_ANNOTATION_TYPE:
                process_species(
                    formatted_annotations=formatted_annotations, bbox_id=bbox_id, bbox_obj=bbox_obj, annotator=annotator
                )
            elif annotation_type == ACTIVITY_ANNOTATION_TYPE:
                process_activity(
                    formatted_annotations=formatted_annotations, bbox_id=bbox_id, bbox_obj=bbox_obj, annotator=annotator
                )

    # Check the species tagged, and ensure there's only 1 for batch tagging
    if len(batch_tag_images) > 0:
        logging.info("Batch tag images selected. Attempting to annotate all bboxes...")
        annotation = list(set(item["category"] for item in formatted_annotations.values()))

        if len(annotation) == 0:
            logging.error("No annotations to apply to batch tag burst images. Skipping.")
        elif len(annotation) > 1:
            logging.error(
                "Cannot batch tag burst images when more than 1 species was annotated for current image. Skipping."
            )
        else:
            tag_batch(
                annotation_type=annotation_type,
                batch_tag_images=batch_tag_images,
                category=annotation[0],
                annotator=annotator,
            )


# Tag multiple images at once, by applying the current image's selection to all bboxes in the other images
def tag_batch(annotation_type, batch_tag_images, category, annotator):
    for image_id in batch_tag_images:
        image = Image.objects.get(id=image_id)
        bboxes = BoundingBox.objects.filter(image=image, validity__in=["UNCERTAIN", "VALID"])

        for bbox in bboxes:
            # Store the category with formatted annotations structure
            formatted_annotations = {}
            formatted_annotations[bbox.id] = {}
            formatted_annotations[bbox.id]["category"] = category
            formatted_annotations[bbox.id]["confidence"] = 1.0

            if annotation_type == SPECIES_ANNOTATION_TYPE:
                process_species(
                    formatted_annotations=formatted_annotations, bbox_id=bbox.id, bbox_obj=bbox, annotator=annotator
                )
            elif annotation_type == ACTIVITY_ANNOTATION_TYPE:
                process_activity(
                    formatted_annotations=formatted_annotations, bbox_id=bbox.id, bbox_obj=bbox, annotator=annotator
                )
        image.species_checked_by.add(annotator)
        image.save()

        logging.info(f"Batch tagging for image {image_id} successful - annotated as {category}.")


# Handles additions, deletions, and updates to image bboxes
def handle_changes(annotation_type, initial_bboxes, formatted_annotations, image, user, annotator, batch_tag_images):
    # Check if annotation type is valid
    if annotation_type not in [SPECIES_ANNOTATION_TYPE, ACTIVITY_ANNOTATION_TYPE]:
        logging.error(f"Invalid annotation type given for processor function: {annotation_type}")
        return False

    # First handle all deletions
    handle_bbox_deletions(
        initial_bboxes=initial_bboxes,
        formatted_annotations=formatted_annotations,
        user=user,
        annotator=annotator,
        image=image,
    )

    # Add boxes
    handle_bbox_additions(
        annotation_type=annotation_type,
        initial_bboxes=initial_bboxes,
        formatted_annotations=formatted_annotations,
        image=image,
        annotator=annotator,
    )

    # Handle bbox updates
    handle_bbox_updates(
        annotation_type, initial_bboxes, formatted_annotations, image, user, annotator, batch_tag_images
    )

    # Set the image to checked by the annotator for the annotation type
    set_image_checked_by(annotation_type=annotation_type, image=image, annotator=annotator)

    image.save()
    logging.info("Successfully updated all bounding boxes")

    return True


# Create or vote on the category after inferring it
def handle_inference(category, bbox_obj, annotator):
    target_category = Category.objects.filter(bounding_box=bbox_obj, name=category)

    if target_category.exists():
        category_obj = target_category.first()

        vote(category_obj, annotator, accept=True)
        # Delete duplicate categories
        target_category.exclude(id=category_obj.id).delete()
    else:
        create_category({"category": category, "confidence": 1}, bbox_obj, annotator)

    # Vote on the bbox as well
    vote(bbox_obj, annotator, accept=True)

    # Cast a reject vote for all other annotations
    other_categories = Category.objects.filter(bounding_box=bbox_obj).exclude(name=category)

    for category in other_categories:
        # Delete duplicate categories with same name
        Category.objects.filter(~Q(id=category.id), bounding_box=bbox_obj, name=category).delete()
        vote(category, annotator, accept=False)

    # Delete old 'unannotated' categories as they cause issues
    Category.objects.filter(bounding_box=bbox_obj, name="unannotated").delete()


# Infer the Category based on the Species annotation if possible
def infer_category(species_name, bbox_obj, annotator):
    species_group = SpeciesName.objects.get(name=species_name).species_group

    if species_group == "HUMAN":
        handle_inference(category=PERSON_CATEGORY, bbox_obj=bbox_obj, annotator=annotator)

    elif species_group in ["WILD", "DOMESTIC"]:
        handle_inference(category=ANIMAL_CATEGORY, bbox_obj=bbox_obj, annotator=annotator)

    elif species_group == "VEHICLE":
        handle_inference(category=VEHICLE_CATEGORY, bbox_obj=bbox_obj, annotator=annotator)
    else:
        logging.info(f"Unable to infer category for {species_name}. Adding 'unknown' Category object.")
        handle_inference(category=UNKNOWN_CATEGORY, bbox_obj=bbox_obj, annotator=annotator)


def process_species(formatted_annotations, bbox_id, bbox_obj, annotator):
    if formatted_annotations[bbox_id]["category"]:
        species_name_obj = SpeciesName.objects.get(name=formatted_annotations[bbox_id]["category"])
        logging.info(f"Vote for {species_name_obj.name} by {annotator} detected on box {bbox_id}.")

        try:
            species_obj = Species.objects.get(bounding_box=bbox_obj, name=species_name_obj)

            if species_obj.created_by != annotator:
                vote(species_obj, annotator, accept=True)
        except ObjectDoesNotExist:
            species_obj = Species.objects.create(
                bounding_box=bbox_obj,
                name=species_name_obj,
                created_by=annotator,
                confidence=formatted_annotations[bbox_id]["confidence"],
            )

        # Cast a reject vote for all other annotations
        for species in Species.objects.filter(~Q(id=species_obj.id), bounding_box=bbox_obj):
            vote(species, annotator, accept=False)

        # Infer the category based on selected Species
        infer_category(species_name=species_name_obj.name, bbox_obj=bbox_obj, annotator=annotator)
    else:
        species_obj = None


def process_activity(formatted_annotations, bbox_id, bbox_obj, annotator):
    if formatted_annotations[bbox_id]["category"]:
        activity_type_obj = ActivityType.objects.get(name=formatted_annotations[bbox_id]["category"])
        try:
            activity_obj = Activity.objects.get(bounding_box=bbox_obj, name=activity_type_obj)
            if activity_obj.created_by != annotator:
                vote(activity_obj, annotator, accept=True)

        except ObjectDoesNotExist:
            activity_obj = Activity.objects.create(
                bounding_box=bbox_obj,
                name=activity_type_obj,
                created_by=annotator,
                confidence=formatted_annotations[bbox_id]["confidence"],
            )

        # Cast a reject vote for all other annotations
        for activity in Activity.objects.filter(~Q(id=activity_obj.id), bounding_box=bbox_obj):
            vote(activity, annotator, accept=False)
    else:
        activity_obj = None


def get_automation_annotator() -> Annotator:
    """Return the dedicated automation bot Annotator used for single-human auto-approvals.

    Lazily creates a distinct ``Bot`` (``AUTOMATION_BOT_NAME``) and a bot ``Annotator`` carrying
    ``automation_criteria=SINGLE_HUMAN_RULE``. The criterion makes the annotator count as an
    override authority in the voting logic (see ``_is_staff_or_expert``), so its single accept vote
    completes the annotation without additional consensus. Using a Bot separate from the detection
    MegaDetector keeps ordinary detection votes at normal weight while only this annotator carries
    expert-equivalent weight.

    The ``automation_criteria`` field also serves as the durable, parsable audit marker of an
    automated decision: which model (via the bot FK) under which criterion.

    Returns:
        The bot ``Annotator`` used for automated single-human approvals.
    """
    detection_task_type = "Object Detection"
    detection_model_api_url = f"{settings.MEGADETECTOR_URL}/annotate/" if settings.MEGADETECTOR_URL else None

    bot, created = Bot.objects.get_or_create(
        name=AUTOMATION_BOT_NAME,
        version=AUTOMATION_BOT_VERSION,
        defaults={"task_type": detection_task_type, "model_api_url": detection_model_api_url},
    )
    if created:
        logging.info(f"Automation bot '{AUTOMATION_BOT_NAME}' created for automated approvals.")
    else:
        # Backfill provenance fields on a pre-existing bot (e.g. one created before this change)
        # so its row stays consistent with the other MegaDetector bot rows.
        bot_updates = {}
        if bot.task_type != detection_task_type:
            bot_updates["task_type"] = detection_task_type
        if detection_model_api_url and bot.model_api_url != detection_model_api_url:
            bot_updates["model_api_url"] = detection_model_api_url
        if bot_updates:
            for field, value in bot_updates.items():
                setattr(bot, field, value)
            bot.save(update_fields=list(bot_updates))

    annotator, created = Annotator.objects.get_or_create(
        type="bot",
        bot=bot,
        defaults={"automation_criteria": SINGLE_HUMAN_RULE},
    )
    if created:
        logging.info("Automation bot annotator created.")
    elif annotator.automation_criteria != SINGLE_HUMAN_RULE:
        # Backfill the criterion if the annotator pre-existed without it.
        annotator.automation_criteria = SINGLE_HUMAN_RULE
        annotator.save(update_fields=["automation_criteria"])

    return annotator


def auto_approve_single_human(
    image: Image,
    confidence_cutoff: float | None = None,
    *,
    automation_annotator: Annotator | None = None,
) -> bool:
    """Auto-complete an image if it contains exactly one high-confidence human bounding box.

    When the image has a single bounding box whose category is `person` and whose confidence meets
    the supplied cutoff (or `settings.SINGLE_HUMAN_AUTO_APPROVE_CONFIDENCE` by default), the
    automation bot annotator votes to accept the box and its category. This completes the category
    pipeline through the normal voting logic, while the species pipeline is marked complete
    directly because a human-only image has no wildlife to identify. The automation annotator's
    ``automation_criteria`` is the audit marker of the decision.

    Args:
        image: The processed image to evaluate. Must already have `processed=True`.
        confidence_cutoff: Minimum bounding-box confidence. Uses the configured default when None.
        automation_annotator: An already-resolved automation annotator. Backlog callers should
            pass this to avoid repeating the bot and annotator lookups for every image.

    Returns:
        True if the image qualified and was auto-approved, False otherwise.
    """
    ############### eligibility check ###############
    bounding_boxes = list(BoundingBox.objects.filter(image=image))
    if len(bounding_boxes) != 1:
        return False

    bbox = bounding_boxes[0]
    cutoff = settings.SINGLE_HUMAN_AUTO_APPROVE_CONFIDENCE if confidence_cutoff is None else confidence_cutoff

    category = Category.objects.filter(bounding_box=bbox, name=PERSON_CATEGORY).first()
    if category is None or bbox.confidence < cutoff:
        return False

    logging.info(f"Auto-approving single-human image {image.id} (confidence {bbox.confidence} >= {cutoff}).")

    ############### cast automation votes ###############
    # Imported lazily to avoid a circular import (views.annotation imports from this module).
    from images.views.annotation import calculateCategoryAnnotationFlags

    annotator = automation_annotator or get_automation_annotator()
    vote(bbox, annotator, accept=True)
    vote(category, annotator, accept=True)

    ############### complete pipelines ###############
    # Category completes through the normal voting logic (the expert vote resolves the box + category).
    calculateCategoryAnnotationFlags(image)

    # Species has no annotation object to vote on for a human-only image, so set it directly.
    image.species_pipeline_complete = True

    # Re-set and re-save the image so it won't be caught in the queue query. This is initially set
    # right when the bounding box is created and rather than touching that code we can do this.
    image.has_uncertain_bbox = image.boundingbox_set.filter(validity="UNCERTAIN").exists()
    image.save()

    return True


# Refactoring of all three processor functions
def process_annotations(
    annotation_type: str,
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
    social_media_worthy_vote: int,
    batch_tag_images: list,
    staff_review_needed: bool = False,
    image_reported: bool | None = None,
    skip: bool = False,
):
    # Get the annotator object for the current user
    annotator, created = Annotator.objects.get_or_create(type="human", human=user)
    if created:
        logging.info(f"Annotator object for user '{user.name}' successfully created")
    else:
        logging.info(f"Annotator object for user '{user.name}' already exists. Successfully retrieved.")

    # Add the annotator to the image's viewed by list
    image = Image.objects.get(id=image_id)
    logging.info("Successfully retrieved image object")

    # Update the staff review flag
    image.staff_review_needed = bool(staff_review_needed)

    # Update the image reported flag
    # - None: preserve current value (not sent from frontend)
    # - True: set to True (user reporting or staff checking)
    # - False: set to False (staff explicitly clearing)
    if image_reported is not None:
        image.image_reported = image_reported

    # If the user skipped this, add the user to the image skipped list & move on
    if skip:
        logging.info("User skipped this image. Adding to skipped list")
        set_image_skipped_by(annotation_type=annotation_type, image=image, annotator=annotator)
        image.save()
        return True

    # Update the image's social media worthy status
    image.social_media_worthy += social_media_worthy_vote

    # Handle additions, deletions, and updates to image bboxes
    handler_success = handle_changes(
        annotation_type=annotation_type,
        # Prep the annotations data
        # Format the annotorious annotations
        initial_bboxes={bbox["id"]: bbox for bbox in initial_bboxes},
        # Convert initial boxes into the same structure
        formatted_annotations=flatten_annotorious_annotations(annotations),
        image=image,
        user=user,
        annotator=annotator,
        batch_tag_images=batch_tag_images,
    )

    return handler_success


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_species_annotations(
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
    social_media_worthy_vote: int,
    batch_tag_images: list,
    staff_review_needed: bool = False,
    image_reported: bool = False,
    skip: bool = False,
) -> bool:
    """Function to process a list of annotations for MegaDetector's Object Detection model

    Annotations follow the Annotorious format
    """
    return process_annotations(
        SPECIES_ANNOTATION_TYPE,
        image_id=image_id,
        annotations=annotations,
        initial_bboxes=initial_bboxes,
        user=user,
        social_media_worthy_vote=social_media_worthy_vote,
        staff_review_needed=staff_review_needed,
        image_reported=image_reported,
        skip=skip,
        batch_tag_images=batch_tag_images,
    )


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_activity_annotations(
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
    social_media_worthy_vote: int,
    batch_tag_images: list,
    staff_review_needed: bool = False,
    image_reported: bool = False,
    skip: bool = False,
) -> bool:
    """Function to process a list of annotations for MegaDetector's Object Detection model

    Annotations follow the Annotorious format
    """
    return process_annotations(
        ACTIVITY_ANNOTATION_TYPE,
        image_id=image_id,
        annotations=annotations,
        initial_bboxes=initial_bboxes,
        user=user,
        social_media_worthy_vote=social_media_worthy_vote,
        staff_review_needed=staff_review_needed,
        image_reported=image_reported,
        skip=skip,
        batch_tag_images=batch_tag_images,
    )
