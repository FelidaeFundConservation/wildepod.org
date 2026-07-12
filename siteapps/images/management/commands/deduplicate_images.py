# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import time
from concurrent.futures import ThreadPoolExecutor

import requests
import yolov9
from colorama import Back, Fore, Style
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Case, Count, Exists, F, OuterRef, Prefetch, Q, When
from images.models import Annotator, BoundingBox, Category, Image, Upload
from images.views import activity_pipeline_query, species_pipeline_query
from images.views.annotation import (
    calculateActivityAnnotationFlags,
    calculateCategoryAnnotationFlags,
    calculateSpeciesAnnotationFlags,
)
from PIL import Image as PILImage
from pyexpat import model


class Command(BaseCommand):
    help = "Delete images with duplicate content hashes in the database."

    def add_arguments(self, parser):
        parser.add_argument("--make_changes", action="store_true", help="Flag to enable saving the changes.")

    def handle(self, *args, **options):
        print("\n================================")
        if options.get("make_changes"):
            print(f"NOTE: {Fore.GREEN}Changes are enabled.{Style.RESET_ALL} Duplicate images will be deleted.")
        else:
            print(Fore.YELLOW + "NOTE: Changes are not enabled. Duplicates will not be deleted from the database.")

        print("================================\n")

        duplicate_hashes = (
            Image.objects.values("dropbox_content_hash")
            .annotate(hash_count=Count("dropbox_content_hash"))
            .filter(hash_count__gt=1)
        )

        duplicate_hash_values = {item["dropbox_content_hash"] for item in duplicate_hashes}

        hash_count = 0
        total_hash_count = len(duplicate_hash_values)
        start_time = time.time()

        print(f"{total_hash_count} duplicate hashes found in the database.")

        def delete_duplicates(hash):
            nonlocal start_time
            nonlocal hash_count
            hash_count += 1

            if (hash_count % 50) == 0:
                completion_percentage = (hash_count / total_hash_count) * 100

                print(
                    f"{Fore.YELLOW}\n==================================="
                    f"{Fore.YELLOW}\nOperation Status ({completion_percentage:.2f}%)"
                    f"{Fore.YELLOW}\n==================================={Style.RESET_ALL}"
                    f"\nTime elapsed: {time.time() - start_time:.2f} seconds"
                    f"\nHashes checked: {hash_count} of {total_hash_count}"
                    f"\n",
                    end="\r",
                    flush=True,
                )

            images = Image.objects.filter(dropbox_content_hash=hash).order_by("created")
            first_image = images.first()

            if options.get("make_changes"):
                images.exclude(id=first_image.id).delete()
            else:
                print(f"{images.count() - 1} image(s) to delete.")

        MAX_THREADS = 10
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            list(executor.map(delete_duplicates, duplicate_hash_values))
