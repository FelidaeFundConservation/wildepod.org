import time

from django.db import connection
from django.db.models import Exists, OuterRef, Prefetch, Q
from images.models import Annotator, BoundingBox, Category, Image

start_time = time.time()

make_changes = False  # Set to True ONLY if you want to batch update the database!


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


images = Image.objects.filter(
    Q(bbox_checked_by__type="human"), Q(bbox_checked_by__human__is_staff=True)
).prefetch_related(
    "bbox_checked_by",
    "bbox_checked_by__human",
    Prefetch(
        "boundingbox_set",
        queryset=BoundingBox.objects.prefetch_related("accepted_by", "accepted_by__human", "category_set"),
    ),
)

initial_queries = len(connection.queries)

image_count = 0
staff_count = 0
nonstaff_count = 0
checked_by_count = 0
boxes_count = 0
fixed_count = 0

# mismatch_staff_annotations = 0
# mismatch_staff = {}

# These fields track the unlikely instances where the staff users annotations were actually recorded!
staff_nobug_annotations = 0
staff_nobug_dict = {}

# multiple_categories = 0

for image in images:
    image_count += 1
    checked_bys = image.bbox_checked_by.all()
    boxes = image.boundingbox_set.all()
    # Get all the annotator ids in the associated bounding boxes accepted_by fields
    accepted_by_annotator_ids = [annotator.id for box in boxes for annotator in box.accepted_by.all()]

    for checked_by_annotator in checked_bys:
        if checked_by_annotator.type == "human":
            checked_by_count += 1
            if checked_by_annotator.human.is_staff:
                staff_count += 1
                # Check for the unlikely case where the staff users have made annotations that were recorded
                # This is proabably because they were normal users when the annotations were made, and then later became staff
                if checked_by_annotator.id in accepted_by_annotator_ids:
                    staff_nobug_annotations += 1
                    staff_nobug_dict[checked_by_annotator.id] = staff_nobug_dict.get(checked_by_annotator.id, 0) + 1
                else:
                    for box in boxes:
                        annotator = checked_by_annotator
                        categories = box.category_set.all()
                        if len(categories) >= 1:
                            if make_changes:
                                vote(box, annotator, accept=True)
                                vote(categories[0], annotator, accept=True)
                            fixed_count += 1
            else:
                nonstaff_count += 1

    # print("  -- Extra sanity checks section -- ")
    # for box in boxes:
    #     boxes_count += 1
    #     accepted_by = box.accepted_by.all()
    #     for annotator in accepted_by:
    #         if annotator.type == "human":
    #             if annotator.human.is_staff:
    #                 mismatch_staff_annotations += 1
    #                 mismatch_staff[annotator.id] = mismatch_staff.get(annotator.id, 0) + 1
    #                 print(f" STAFF ANNOTATION ???   Staff: {annotator.human.name}, Annotator id: {annotator.id}")
    #                 print(f"    User created at {annotator.human.created} modified at {annotator.human.modified}")

    #     categories = box.category_set.all()
    #     if len(categories) > 1:
    #         multiple_categories += 1
    #         print(f"    Multiple categories for box {box.id}")
    #         for category in categories:
    #             print(f"      Category name {category.name}")
    #         print(f"      Dropbox share URL {image.dropbox_share_url}")
    #         print(f"      Dropbox name {image.dropbox_file_name}")
    #         print(f"      Dropbox path {image.dropbox_file_path}")
    #         print(f"      Dropbox path display {image.dropbox_file_path_display}")
    #     elif len(categories) == 1:
    #         pass
    #     else:
    #         print(f"    No category for box {box.id}")

    if (image_count % 1000) == 0:
        print(
            f"Image count {image_count}, Current checked_by counts (staff/all): {staff_count} / {checked_by_count}, time taken: {time.time() - start_time:.0f} seconds"
        )

print(f"Total images: {image_count}")
print(f"Total checked_by (staff/all): {staff_count} / {checked_by_count}")
print(f"Total bounding boxes: {boxes_count}")
print(f"Total fixed: {fixed_count}")
# print(f"Total mismatch staff annotations: {mismatch_staff_annotations}")
# print(mismatch_staff)
print(f"Total second mismatch staff annotations: {staff_nobug_annotations}")
print(staff_nobug_dict)

# print(f"Total multiple categories: {multiple_categories}")

end_time = time.time()
total_time = end_time - start_time

print("Total time taken: {:.2f} seconds".format(total_time))
