import logging
from typing import Any, Dict

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from images.models import Activity, ActivityType, Annotator, BoundingBox, Category, Image, Species, SpeciesName

# TODO: This entire module is very hacky and needs to be refactored


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
    obj.save()
    return


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


def create_bbox(annotation_dict: Dict[str, Any], image_obj: Image, annotator: Annotator):
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
    create_category(annotation_dict, bbox_obj, annotator)
    return


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_md_annotations(
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
    social_media_worthy: bool = False,
    skip: bool = False,
):
    """Function to process a list of annotations for MegaDetector's Object Detection model

    Annotations follow the Annotorious format
    """
    # Get the annotator object for the current user
    annotator, created = Annotator.objects.get_or_create(type="human", human=user)
    if created:
        logging.info(f"Annotator object for user '{user.name}' successfully created")
    else:
        logging.info(f"Annotator object for user '{user.name}' already exists. Successfully retrieved.")

    # Add the annotator to the image's viewed by list
    image = Image.objects.get(id=image_id)
    logging.info("Successfully retrieved image object")

    # If the user skipped this, add the user to the image skipped list & move on
    if skip:
        logging.info("User skipped this image. Adding to skipped list")
        image.bbox_skipped_by.add(annotator)
        image.save()
        return True

    # Update the image's social media worthy status
    if social_media_worthy:
        image.social_media_worthy += 1

    # Prep the annotations data
    # Format the annotorious annotations
    formatted_annotations = flatten_annotorious_annotations(annotations)
    # Convert initial boxes into the same structure
    initial_bboxes = {bbox["id"]: bbox for bbox in initial_bboxes}

    # First handle all deletions
    for bbox_id in initial_bboxes:
        if bbox_id not in formatted_annotations:
            # First get the bounding box
            bbox_obj = BoundingBox.objects.get(id=bbox_id)
            # If the annotator is the same as the current user or if it is a staff user, then the object can be deleted
            if user.is_staff or bbox_obj.created_by == annotator:
                # Then delete it
                bbox_obj.delete()
            else:
                vote(bbox_obj, annotator, accept=False)
    logging.info("Successfully removed all deleted bounding boxes")

    # Next, handles all additions
    for bbox_id in formatted_annotations:
        # If the annotation is not in the initial list, it is a new annotation
        if bbox_id not in initial_bboxes:
            # Create the bounding box
            create_bbox(formatted_annotations[bbox_id], image, annotator)

    logging.info("Successfully created all new bounding boxes")

    # TODO: Extremely gnarly code. Must refactor
    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        if bbox_id in formatted_annotations:
            # Get the initial bounding box & category object
            bbox_obj = BoundingBox.objects.get(id=bbox_id)
            category_obj = Category.objects.get(bounding_box=bbox_obj, name=initial_bboxes[bbox_id]["category"])

            # First handle the case of 'accept' votes. This can happen in 3 cases,
            # 1) The user is staff
            # 2) The user is the same as the annotator who created the bounding box
            # 3) The user is a regular annotator but the bounding box coordinates haven't changed
            if (
                user.is_staff
                or bbox_obj.created_by == annotator
                or all(
                    [
                        abs(bbox_obj.x - formatted_annotations[bbox_id]["x"]) < 0.02,
                        abs(bbox_obj.y - formatted_annotations[bbox_id]["y"]) < 0.02,
                        abs(bbox_obj.w - formatted_annotations[bbox_id]["w"]) < 0.02,
                        abs(bbox_obj.h - formatted_annotations[bbox_id]["h"]) < 0.02,
                    ]
                )
            ):
                # If the user is staff or annotator, we directly edit the bounding box
                if user.is_staff or bbox_obj.created_by == annotator:
                    bbox_obj.x = formatted_annotations[bbox_id]["x"]
                    bbox_obj.y = formatted_annotations[bbox_id]["y"]
                    bbox_obj.w = formatted_annotations[bbox_id]["w"]
                    bbox_obj.h = formatted_annotations[bbox_id]["h"]
                    category_obj.name = formatted_annotations[bbox_id]["category"]
                    category_obj.confidence = formatted_annotations[bbox_id]["confidence"]
                    bbox_obj.save()
                    category_obj.save()

                # Now set the 'accept' votes for bounding box and category

                # Update accept/reject if not created by the same user
                vote(bbox_obj, annotator, accept=True)

                # Next, cast a vote for the category label if it is the same
                if initial_bboxes[bbox_id]["category"] == formatted_annotations[bbox_id]["category"]:
                    # Vote cast only if the user is not the creator
                    vote(category_obj, annotator, accept=True)
                # If it isn't the same, then vote reject on the existing category & create/update a new category
                else:
                    vote(category_obj, annotator, accept=False)
                    # If the category exists, add a vote to it
                    try:
                        new_category_obj = Category.objects.get(
                            bounding_box=bbox_obj,
                            name=formatted_annotations[bbox_id]["category"],
                        )
                        vote(new_category_obj, annotator, accept=True)
                    # If not, create the label & link it to the bounding box
                    except ObjectDoesNotExist:
                        create_category(formatted_annotations[bbox_id], bbox_obj, annotator)

            else:
                # Handle the cases of 'reject' votes

                # Original bounding box was modified significantly by the annotator. Cast a reject vote on the original.
                vote(bbox_obj, annotator, accept=False)
                # Create a new bounding box
                create_bbox(formatted_annotations[bbox_id], image, annotator)

    # Set image to "checked" by the annotator
    image.bbox_checked_by.add(annotator)
    image.save()

    logging.info("Successfully updated all bounding boxes")
    return True


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_species_annotations(
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
    skip: bool = False,
) -> bool:
    """Function to process a list of annotations for MegaDetector's Object Detection model

    Annotations follow the Annotorious format
    """
    # Get the annotator object for the current user
    annotator, created = Annotator.objects.get_or_create(type="human", human=user)
    if created:
        logging.info(f"Annotator object for user '{user.name}' successfully created")
    else:
        logging.info(f"Annotator object for user '{user.name}' already exists. Successfully retrieved.")
    # Add the annotator to the image's viewed by list
    image = Image.objects.get(id=image_id)
    logging.info("Successfully retrieved image object")

    # If the user skipped this, add the user to the image skipped list & move on
    if skip:
        logging.info("User skipped this image. Adding to skipped list")
        image.species_skipped_by.add(annotator)
        image.save()
        return True

    # Prep the annotations data
    # Format the annotorious annotations
    formatted_annotations = flatten_annotorious_annotations(annotations)
    # Convert initial boxes into the same structure
    initial_bboxes = {bbox["id"]: bbox for bbox in initial_bboxes}
    # If any bounding box is missing, return an error
    # for bbox_id in initial_bboxes:
    #    if bbox_id not in formatted_annotations:
    #        logging.error("Error: Bounding boxes were deleted when annotating species.")
    #        return False

    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        # Get the initial bounding box & category object
        bbox_obj = BoundingBox.objects.get(id=bbox_id)
        if bbox_id in formatted_annotations:
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
            else:
                species_obj = None

    # Set image to "checked" by the annotator
    image.species_checked_by.add(annotator)
    image.save()

    logging.info("Successfully updated all bounding boxes")
    return True


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_activity_annotations(
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
    skip: bool = False,
) -> bool:
    """Function to process a list of annotations for MegaDetector's Object Detection model

    Annotations follow the Annotorious format
    """
    # Get the annotator object for the current user
    annotator, created = Annotator.objects.get_or_create(type="human", human=user)
    if created:
        logging.info(f"Annotator object for user '{user.name}' successfully created")
    else:
        logging.info(f"Annotator object for user '{user.name}' already exists. Successfully retrieved.")
    # Add the annotator to the image's viewed by list
    image = Image.objects.get(id=image_id)
    logging.info("Successfully retrieved image object")

    # If the user skipped this, add the user to the image skipped list & move on
    if skip:
        logging.info("User skipped this image. Adding to skipped list")
        image.activity_skipped_by.add(annotator)
        image.save()
        return True

    # Prep the annotations data
    # Format the annotorious annotations
    formatted_annotations = flatten_annotorious_annotations(annotations)
    # Convert initial boxes into the same structure
    initial_bboxes = {bbox["id"]: bbox for bbox in initial_bboxes}
    # If any bounding box is missing, return an error
    # for bbox_id in initial_bboxes:
    # if bbox_id not in formatted_annotations:
    # logging.error("Error: Bounding boxes were deleted when annotating activity.")
    # return False

    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        # Get the initial bounding box & category object
        bbox_obj = BoundingBox.objects.get(id=bbox_id)
        if bbox_id in formatted_annotations:
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
            else:
                activity_obj = None

    # Set image to "checked" by the annotator
    image.activity_checked_by.add(annotator)
    image.save()

    logging.info("Successfully updated all bounding boxes")
    return True
