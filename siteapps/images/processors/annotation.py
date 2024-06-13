import logging
from typing import Any, Dict

from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db.models import Count, Q, Sum
from images.models import Activity, ActivityType, Annotator, BoundingBox, Category, Image, Species, SpeciesName, Upload

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
    """Helper function to cast a vote for an object"""
    if accept:
        obj.accepted_by.add(annotator)
        obj.rejected_by.remove(annotator)
    else:
        obj.accepted_by.remove(annotator)
        obj.rejected_by.add(annotator)

        # Undo creation if reannotating
        if obj.created_by == annotator:
            if obj.accepted_by.count() == 0:
                obj.delete()
            else:
                other_annotator = obj.accepted_by.first()
                obj.created_by = other_annotator
                obj.accepted_by.remove(other_annotator)
                obj.save()
        else:
            obj.save()
    return


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

    return


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
                    vote(bbox_obj, annotator, accept=False)
                    bbox_obj.validity = "Invalid"
                    bbox_obj.save()
                    logging.info(f"Rejected bounding box with id {bbox_id}. Object still exists in rejected state.")
            except ObjectDoesNotExist:
                logging.info(f"Bounding box with id {bbox_id} doesn't exist in image {image.id}. Skipping deletion.")

    logging.info("Successfully removed all deleted bounding boxes")


def handle_bbox_updates(
    annotation_type, initial_bboxes, formatted_annotations, image, user, annotator, batch_tag_images
):
    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        if bbox_id in formatted_annotations:
            # Get the initial bounding box & category object
            try:
                bbox_obj = BoundingBox.objects.get(id=bbox_id)
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
        species_annotation = list(set(item["category"] for item in formatted_annotations.values()))

        if len(species_annotation) == 0:
            logging.error("No annotations to apply to batch tag burst images. Skipping.")
        elif len(species_annotation) > 1:
            logging.error(
                "Cannot batch tag burst images when more than 1 species was annotated for current image. Skipping."
            )
        else:
            tag_batch(batch_tag_images=batch_tag_images, category=species_annotation[0], annotator=annotator)


# Tag multiple images at once, by applying the current image's selection to all bboxes in the other images
def tag_batch(batch_tag_images, category, annotator):
    for image_id in batch_tag_images:
        image = Image.objects.get(id=image_id)
        bboxes = BoundingBox.objects.filter(image=image, validity__in=["Uncertain", "Valid"])

        for bbox in bboxes:
            # Store the category with formatted annotations structure
            formatted_species = {}
            formatted_species[bbox.id] = {}
            formatted_species[bbox.id]["category"] = category
            formatted_species[bbox.id]["confidence"] = 1.0

            process_species(
                formatted_annotations=formatted_species, bbox_id=bbox.id, bbox_obj=bbox, annotator=annotator
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
    staff_review_needed: bool = False,
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
        skip=skip,
    )
