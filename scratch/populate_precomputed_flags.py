import time

from django.db import connection
from django.db.models import Exists, OuterRef, Prefetch, Q
from images.models import Annotator, BoundingBox, Category, Image
from images.views.annotation import calculateCategoryAnnotationFlags, calculateSpeciesAnnotationFlags, calculateActivityAnnotationFlags

start_time = time.time()

make_changes = False  # Set to True ONLY if you want to batch update the database!

# Assuming that if no flag is True, the image has yet to be checked.
images = Image.objects.filter(
    Q(category_pipeline_complete=False) &
    Q(species_pipeline_complete=False) &
    Q(activity_pipeline_complete=False) &
    Q(has_animals=False) &
    Q(has_humans=False) &
    Q(has_vehicles=False) &
    Q(has_wild_animals=False)
)

image_count = 0
total_image_count = images.count()

category_pipeline_complete_count = 0
species_pipeline_complete_count = 0
activity_pipeline_complete_count = 0

has_animals_count = 0
has_humans_count = 0
has_vehicles_count = 0
has_wild_animals_count = 0

for image in images:
    image_count += 1

    # Handles all checks and flag setting.
    category_debug_info = calculateCategoryAnnotationFlags(image)
    species_debug_info = calculateSpeciesAnnotationFlags(image)
    activity_debug_info = calculateActivityAnnotationFlags(image)

    # Keeping track of stats
    if category_debug_info["pipeline_flags"]["has_humans"] == True:
        has_humans_count += 1
    if category_debug_info["pipeline_flags"]["has_animals"] == True:
        has_animals_count += 1
    if category_debug_info["pipeline_flags"]["has_vehicles"] == True:
        has_vehicles_count += 1
    if category_debug_info["pipeline_flags"]["category_pipeline_complete"] == True:
        category_pipeline_complete_count += 1

    if species_debug_info["pipeline_flags"]["has_wild_animals"] == True:
        has_wild_animals_count += 1
    if species_debug_info["pipeline_flags"]["species_pipeline_complete"] == True:
        species_pipeline_complete_count += 1

    if activity_debug_info["pipeline_flags"]["activity_pipeline_complete"] == True:
        activity_pipeline_complete_count += 1

    if (image_count % 1000) == 0:
        completion_percentage = (image_count / total_image_count) * 100

        print(
            "\n==================================="
            f"\nOperation Status ({completion_percentage:.2f}%)"
            "\n==================================="
            f"\nTime elapsed: {time.time() - start_time:.2f} seconds"
            f"\nImages checked: {image_count} of {total_image_count}"
            f"\n\nCategory complete flags set: {category_pipeline_complete_count}, "
            f"\nSpecies complete flags set: {species_pipeline_complete_count}, "
            f"\nActivity complete flags set: {activity_pipeline_complete_count}, "
            f"\nHas animal flags set: {has_animals_count}, "
            f"\nHas humans flags set: {has_humans_count}, "
            f"\nHas vehicles flags set: {has_vehicles_count}, "
            f"\nHas wild animals flags set: {has_wild_animals_count}\n", end="\r", flush=True
        )

    if make_changes:
        image.save()
    else:
        image = None

end_time = time.time()
total_time = end_time - start_time

print("Operation complete. Total time taken: {:.2f} seconds".format(total_time))
print(f"First image checked (local dev link): http://127.0.0.1:8000/images/image/{images[0].id}")
print(f"Last image checked (local dev link): http://127.0.0.1:8000/images/image/{images[len(images) - 1].id}")


