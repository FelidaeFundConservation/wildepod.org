import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from images.models import Annotator, BoundingBox, Category, Image, Species, SpeciesName

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
        [x, y, w, h] = annotation["target"]["selector"]["value"].split(":")[1].split(",")
        [x, y, w, h] = list(map(lambda x: round(float(x), 6) / 100, [x, y, w, h]))

        # Append the annotation to the list
        formatted_annotations[clean_uuid] = {
            "id": clean_uuid,
            "category": annotation["body"][0]["value"],
            "confidence": annotation["body"][0]["confidence"],
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        }
    logging.info("Successfully flattened annotorious annotations..")
    return formatted_annotations


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_md_annotations(
    image_id: str,
    annotations: list,
    initial_bboxes: list,
    user: settings.AUTH_USER_MODEL,
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
        return

    image.bbox_checked_by.add(annotator)

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
                # Add the annotator to its rejection list
                bbox_obj.accepted_by.remove(annotator)
                bbox_obj.rejected_by.add(annotator)
                bbox_obj.save()
    logging.info("Successfully deleted all deleted bounding boxes")

    # Next, handles all additions
    for bbox_id in formatted_annotations:
        # If the annotation is not in the initial list, it is a new annotation
        if bbox_id not in initial_bboxes:
            bbox_obj = BoundingBox.objects.create(
                image=image,
                x=formatted_annotations[bbox_id]["x"],
                y=formatted_annotations[bbox_id]["y"],
                w=formatted_annotations[bbox_id]["w"],
                h=formatted_annotations[bbox_id]["h"],
                confidence=formatted_annotations[bbox_id]["confidence"],
                created_by=annotator,
            )
            # Next, create a category annotation for it
            category_obj = Category.objects.create(
                bounding_box=bbox_obj,
                name=formatted_annotations[bbox_id]["category"],
                created_by=annotator,
                confidence=formatted_annotations[bbox_id]["confidence"],
            )
            bbox_obj.save()
    logging.info("Successfully created all new bounding boxes")

    # TODO: Extremely gnarly code. Must refactor
    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        if bbox_id in formatted_annotations:
            # Get the initial bounding box & category object
            bbox_obj = BoundingBox.objects.get(id=bbox_id)
            category_obj = Category.objects.get(bounding_box=bbox_obj, name=initial_bboxes[bbox_id]["category"])

            # If the user is staff or annotator, directly edit the bounding box & category
            if user.is_staff or bbox_obj.created_by == annotator:
                bbox_obj.x = formatted_annotations[bbox_id]["x"]
                bbox_obj.y = formatted_annotations[bbox_id]["y"]
                bbox_obj.w = formatted_annotations[bbox_id]["w"]
                bbox_obj.h = formatted_annotations[bbox_id]["h"]
                category_obj.name = formatted_annotations[bbox_id]["category"]
                category_obj.confidence = formatted_annotations[bbox_id]["confidence"]
                bbox_obj.save()
                category_obj.save()
            # Else, if its a regular annotator
            else:
                # Check if the co-ordinates have changed. If they haven't, count it as an accept/reject vote
                if all(
                    [
                        abs(bbox_obj.x - formatted_annotations[bbox_id]["x"]) < 0.02,
                        abs(bbox_obj.y - formatted_annotations[bbox_id]["y"]) < 0.02,
                        abs(bbox_obj.w - formatted_annotations[bbox_id]["w"]) < 0.02,
                        abs(bbox_obj.h - formatted_annotations[bbox_id]["h"]) < 0.02,
                    ]
                ):
                    # Update accept/reject if not created by the same user
                    bbox_obj.rejected_by.remove(annotator)
                    bbox_obj.accepted_by.add(annotator)
                    bbox_obj.save()
                    # Next, labels can be also be modified if the annotator is staff or if the annotator is the same as the user
                    if initial_bboxes[bbox_id]["category"] == formatted_annotations[bbox_id]["category"]:
                        # Vote cast only if the user is not the creator
                        category_obj.rejected_by.remove(annotator)
                        category_obj.accepted_by.add(annotator)
                        category_obj.save()
                    # Else, check if it exists, if not create it.
                    else:
                        # If the category exists, add a vote to it
                        try:
                            new_category_obj = Category.objects.get(
                                bounding_box=bbox_obj,
                                name=formatted_annotations[bbox_id]["category"],
                            )
                            new_category_obj.rejected_by.remove(annotator)
                            new_category_obj.accepted_by.add(annotator)
                            new_category_obj.save()
                        # If not, create the label & link it to the bounding box
                        except ObjectDoesNotExist:
                            new_category_obj = Category.objects.create(
                                bounding_box=bbox_obj,
                                name=formatted_annotations[bbox_id]["category"],
                                created_by=annotator,
                                confidence=formatted_annotations[bbox_id]["confidence"],
                            )
                            category_obj.rejected_by.add(annotator)
                            category_obj.accepted_by.remove(annotator)
                            category_obj.save()
                # Else if the bounding box was modified by the annotator, treat it as a new bounding box
                else:
                    # Cast a reject vote
                    bbox_obj.rejected_by.add(annotator)
                    bbox_obj.accepted_by.remove(annotator)
                    bbox_obj.save()
                    # No explicit reject vote cast to the category of the previous object
                    # since the category will be created as a new object linked to the new bbox

                    # Create a new bounding box
                    new_bbox_obj = BoundingBox.objects.create(
                        image=image,
                        x=formatted_annotations[bbox_id]["x"],
                        y=formatted_annotations[bbox_id]["y"],
                        w=formatted_annotations[bbox_id]["w"],
                        h=formatted_annotations[bbox_id]["h"],
                        confidence=formatted_annotations[bbox_id]["confidence"],
                        created_by=annotator,
                    )
                    # Next, create a category annotation for it
                    category_obj = Category.objects.create(
                        bounding_box=bbox_obj,
                        name=formatted_annotations[bbox_id]["category"],
                        created_by=annotator,
                        confidence=formatted_annotations[bbox_id]["confidence"],
                    )
                    new_bbox_obj.save()

    logging.info("Successfully updated all bounding boxes")


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
        return True

    # Prep the annotations data
    # Format the annotorious annotations
    formatted_annotations = flatten_annotorious_annotations(annotations)
    # Convert initial boxes into the same structure
    initial_bboxes = {bbox["id"]: bbox for bbox in initial_bboxes}
    # If any bounding box is missing, return an error
    for bbox_id in initial_bboxes:
        if bbox_id not in formatted_annotations:
            logging.error("Error: Bounding boxes were deleted when annotating species.")
            return False

    image.species_checked_by.add(annotator)

    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        # Get the initial bounding box & category object
        bbox_obj = BoundingBox.objects.get(id=bbox_id)
        species_name_obj = SpeciesName.objects.get(name=formatted_annotations[bbox_id]["category"])
        try:
            species_obj = Species.objects.get(bounding_box=bbox_obj, name=species_name_obj)
            if species_obj.created_by != annotator:
                species_obj.rejected_by.remove(annotator)
                species_obj.accepted_by.add(annotator)
        except ObjectDoesNotExist:
            species_obj = Species.objects.create(
                bounding_box=bbox_obj,
                name=species_name_obj,
                created_by=annotator,
                confidence=formatted_annotations[bbox_id]["confidence"],
            )

        # Save the objects
        species_obj.save()
    logging.info("Successfully updated all bounding boxes")
    return True
