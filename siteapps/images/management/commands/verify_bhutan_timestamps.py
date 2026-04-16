"""
Verify Bhutan timestamp assumptions by comparing:
  1. Raw EXIF data from Dropbox images (DateTimeOriginal, OffsetTimeOriginal)
  2. Dropbox metadata time_taken
  3. Stored trigger_timestamp in the database

Modes:
  --per-upload     Sample 1 image per upload per camera station. Most thorough.
  --per-station    Sample N images per camera station (default 2).
  (default)        Sample N images across the full dataset.

This should be run BEFORE fix_bhutan_timestamps to confirm our assumptions are correct.
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import pytz
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from images.models import Image, Upload
from images.utils.dropbox_client import create_dropbox_client
from PIL import Image as PILImage

logger = logging.getLogger(__name__)

# EXIF IFD tag IDs
EXIF_IFD_TAG = 0x8769
TAG_DATETIME_ORIGINAL = 0x9003
TAG_OFFSET_TIME_ORIGINAL = 0x9011

LA_TZ = pytz.timezone("America/Los_Angeles")
BHUTAN_TZ = pytz.timezone("Asia/Thimphu")

# DST transitions for America/Los_Angeles (relevant range)
# Format: (transition_datetime_utc, from_abbrev, to_abbrev)
DST_TRANSITIONS_LA = [
    # 2025
    (datetime(2025, 3, 9, 10, 0, 0), "PST", "PDT"),  # Spring forward
    (datetime(2025, 11, 2, 9, 0, 0), "PDT", "PST"),  # Fall back
    # 2026
    (datetime(2026, 3, 8, 10, 0, 0), "PST", "PDT"),  # Spring forward
    (datetime(2026, 11, 1, 9, 0, 0), "PDT", "PST"),  # Fall back
]


def parse_exif_offset(offset_str):
    """Parse EXIF OffsetTimeOriginal string into (hours_float, category_string).

    For corrupted offsets (minutes > 59), Dropbox ignores the offset entirely,
    so offset_hours = 0.
    """
    if not offset_str:
        return None, "missing"

    offset_str = offset_str.strip()
    match = re.match(r"^([+-])(\d{1,2}):(\d{1,5})$", offset_str)
    if not match:
        return None, f"unparseable:{offset_str}"

    sign = -1 if match.group(1) == "-" else 1
    hours = int(match.group(2))
    minutes = int(match.group(3))

    if minutes > 59:
        return 0, f"corrupted:{offset_str}"

    return sign * (hours + minutes / 60), f"clean:{offset_str}"


def read_exif_from_dropbox(dbx, dropbox_path):
    """Download image from Dropbox and extract EXIF timestamp info."""
    result = {
        "datetime_original": None,
        "offset_time_original": None,
        "offset_hours": None,
        "offset_category": None,
        "error": None,
    }

    try:
        _, response = dbx.files_download(dropbox_path)
        pil_image = PILImage.open(BytesIO(response.content))

        exif_data = pil_image.getexif()
        exif_ifd = exif_data.get_ifd(EXIF_IFD_TAG)

        result["datetime_original"] = exif_ifd.get(TAG_DATETIME_ORIGINAL)
        result["offset_time_original"] = exif_ifd.get(TAG_OFFSET_TIME_ORIGINAL)
        result["offset_hours"], result["offset_category"] = parse_exif_offset(result["offset_time_original"])
    except Exception as e:
        result["error"] = str(e)

    return result


def get_la_dst_label(utc_dt):
    """Return 'PST' or 'PDT' for a given UTC datetime."""
    la_dt = utc_dt.astimezone(LA_TZ)
    return la_dt.strftime("%Z")


def is_near_dst_transition(utc_dt, hours=2):
    """Check if a UTC datetime is within `hours` of a DST transition."""
    for transition_utc, from_abbr, to_abbr in DST_TRANSITIONS_LA:
        transition_aware = pytz.utc.localize(transition_utc)
        diff = abs((utc_dt - transition_aware).total_seconds()) / 3600
        if diff <= hours:
            return True, f"{from_abbr}→{to_abbr} transition"
    return False, None


def compute_fix(stored_utc, offset_hours):
    """Apply the fix formula: UTC → LA → strip tz → add offset → localize Bhutan.

    Returns (corrected_bhutan_dt, intermediate_values_dict).
    """
    la_time = stored_utc.astimezone(LA_TZ)
    dropbox_naive = la_time.replace(tzinfo=None)
    exif_naive = dropbox_naive + timedelta(hours=offset_hours)
    corrected = BHUTAN_TZ.localize(exif_naive)

    return corrected, {
        "la_time": la_time,
        "la_offset": la_time.strftime("%Z (%z)"),
        "dropbox_naive": dropbox_naive,
        "exif_naive": exif_naive,
    }


def verify_fix(image, exif_result):
    """Verify the fix formula for a single image. Returns a result dict."""
    result = {
        "image_id": str(image.pk),
        "dropbox_file_name": image.dropbox_file_name,
        "stored_utc": image.trigger_timestamp,
        "exif_datetime": exif_result["datetime_original"],
        "exif_offset_raw": exif_result["offset_time_original"],
        "exif_offset_hours": exif_result["offset_hours"],
        "offset_category": exif_result["offset_category"],
        "la_dst": get_la_dst_label(image.trigger_timestamp),
        "near_dst_transition": False,
        "dst_transition_info": None,
        "fix_ok": None,
        "fix_error_hours": None,
        "error": exif_result.get("error"),
    }

    near_dst, dst_info = is_near_dst_transition(image.trigger_timestamp)
    result["near_dst_transition"] = near_dst
    result["dst_transition_info"] = dst_info

    if exif_result["error"] or exif_result["datetime_original"] is None or exif_result["offset_hours"] is None:
        return result

    try:
        exif_naive = datetime.strptime(exif_result["datetime_original"], "%Y:%m:%d %H:%M:%S")
        corrected, intermediates = compute_fix(image.trigger_timestamp, exif_result["offset_hours"])
        corrected_naive = corrected.replace(tzinfo=None)
        diff_seconds = (corrected_naive - exif_naive).total_seconds()
        result["fix_ok"] = abs(diff_seconds) < 60
        result["fix_error_hours"] = diff_seconds / 3600
        result["intermediates"] = intermediates
    except ValueError as e:
        result["error"] = f"parse error: {e}"

    return result


class Command(BaseCommand):
    help = "Verify Bhutan timestamp assumptions by reading EXIF data from Dropbox images."

    def add_arguments(self, parser):
        parser.add_argument(
            "--per-upload",
            action="store_true",
            help="Sample 1 image per upload per camera station (most thorough).",
        )
        parser.add_argument(
            "--per-station",
            action="store_true",
            help="Sample N images per camera station.",
        )
        parser.add_argument(
            "--samples-per-station",
            type=int,
            default=2,
            help="Images per station in --per-station mode (default: 2).",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=20,
            help="Total images in default mode (default: 20).",
        )
        parser.add_argument(
            "--camera-station",
            type=str,
            default=None,
            help="Filter by camera station ID (substring match).",
        )

    def handle(self, *args, **options):
        if options["per_upload"]:
            self.handle_per_upload(*args, **options)
        elif options["per_station"]:
            self.handle_per_station(*args, **options)
        else:
            self.handle_random_sample(*args, **options)

    # ──────────────────────────────────────────────────────────────
    # PER-UPLOAD MODE
    # ──────────────────────────────────────────────────────────────
    def handle_per_upload(self, *args, **options):
        camera_station_filter = options["camera_station"]

        dbx = create_dropbox_client()
        if dbx is None:
            self.stderr.write(self.style.ERROR("Could not create Dropbox client."))
            return

        # Get all uploads with images, grouped by camera station
        upload_qs = Upload.objects.filter(images__trigger_timestamp__isnull=False).distinct()
        if camera_station_filter:
            upload_qs = upload_qs.filter(camera_station__station_id__icontains=camera_station_filter)

        upload_qs = upload_qs.select_related("camera_station").order_by(
            "camera_station__station_id", "date_retrieved"
        )

        uploads = list(upload_qs.annotate(image_count=Count("images")))
        total_uploads = len(uploads)

        # Group by station for display
        station_uploads = defaultdict(list)
        for u in uploads:
            station_uploads[u.camera_station.station_id].append(u)

        total_stations = len(station_uploads)
        total_images_in_scope = sum(u.image_count for u in uploads)

        self.stdout.write(
            f"Found {total_uploads} uploads across {total_stations} stations "
            f"({total_images_in_scope} images total).\n"
            f"Will sample 1 image per upload = {total_uploads} Dropbox downloads.\n"
        )

        # Track results
        all_results = []
        station_summaries = {}
        upload_idx = 0

        for station_id in sorted(station_uploads.keys()):
            station_upload_list = station_uploads[station_id]
            station_image_count = sum(u.image_count for u in station_upload_list)

            self.stdout.write(
                f"\n{'='*90}\n"
                f"Station: {station_id} "
                f"({station_image_count} images, {len(station_upload_list)} uploads)"
            )

            station_offsets = set()
            station_categories = set()
            station_pass = 0
            station_fail = 0
            station_error = 0
            station_fail_details = []

            for upload in station_upload_list:
                upload_idx += 1

                # Get first image by trigger_timestamp for this upload
                image = (
                    Image.objects.filter(upload=upload, trigger_timestamp__isnull=False)
                    .order_by("trigger_timestamp")
                    .first()
                )
                if not image:
                    self.stdout.write(f"  Upload {upload.date_retrieved.date()} ({upload.image_count} imgs): no images with timestamps")
                    station_error += 1
                    continue

                # Read EXIF
                exif = read_exif_from_dropbox(dbx, image.dropbox_file_path)
                result = verify_fix(image, exif)
                all_results.append(result)

                # Track per-station
                if result["offset_category"]:
                    station_categories.add(result["offset_category"])
                if result["exif_offset_raw"]:
                    station_offsets.add(result["exif_offset_raw"])

                # Format output line
                date_str = upload.date_retrieved.date()
                offset_str = result["exif_offset_raw"] or "N/A"
                cat_str = result["offset_category"] or "?"
                dst_str = result["la_dst"]
                near_dst = " ⚠DST" if result["near_dst_transition"] else ""

                if result["error"]:
                    status = self.style.WARNING(f"ERR: {result['error'][:60]}")
                    station_error += 1
                elif result["fix_ok"] is True:
                    status = self.style.SUCCESS("OK")
                    station_pass += 1
                elif result["fix_ok"] is False:
                    err_h = result["fix_error_hours"]
                    status = self.style.ERROR(f"WRONG by {err_h:+.1f}h")
                    station_fail += 1
                    station_fail_details.append(result)
                else:
                    status = self.style.WARNING("SKIP")
                    station_error += 1

                self.stdout.write(
                    f"  [{upload_idx:>4}/{total_uploads}] "
                    f"Upload {date_str} ({upload.image_count:>5} imgs)  "
                    f"Offset: {offset_str:<12} Cat: {cat_str:<25} "
                    f"DST: {dst_str}{near_dst:<8} "
                    f"Fix: {status}"
                )

            # Print failure details for this station
            for fail in station_fail_details:
                self.stdout.write(self.style.ERROR(f"\n  FAILURE DETAIL:"))
                self.stdout.write(f"    Image:          {fail['dropbox_file_name']}")
                self.stdout.write(f"    Stored UTC:     {fail['stored_utc']}")
                self.stdout.write(f"    EXIF datetime:  {fail['exif_datetime']}")
                self.stdout.write(f"    EXIF offset:    {fail['exif_offset_raw']} → {fail['exif_offset_hours']}h")
                self.stdout.write(f"    LA DST:         {fail['la_dst']}")
                if fail.get("intermediates"):
                    intr = fail["intermediates"]
                    self.stdout.write(f"    LA time:        {intr['la_time']} ({intr['la_offset']})")
                    self.stdout.write(f"    Dropbox naive:  {intr['dropbox_naive']}")
                    self.stdout.write(f"    Recovered EXIF: {intr['exif_naive']}")
                self.stdout.write(f"    Error:          {fail['fix_error_hours']:+.2f}h")
                if fail["near_dst_transition"]:
                    self.stdout.write(self.style.WARNING(f"    Near DST:       {fail['dst_transition_info']}"))

            station_summaries[station_id] = {
                "image_count": station_image_count,
                "upload_count": len(station_upload_list),
                "offsets": station_offsets,
                "categories": station_categories,
                "pass": station_pass,
                "fail": station_fail,
                "error": station_error,
            }

        # ── GRAND SUMMARY ──
        self.stdout.write("\n\n" + "=" * 120)
        self.stdout.write(self.style.MIGRATE_HEADING("GRAND SUMMARY"))

        total_pass = sum(s["pass"] for s in station_summaries.values())
        total_fail = sum(s["fail"] for s in station_summaries.values())
        total_error = sum(s["error"] for s in station_summaries.values())
        total_checked = total_pass + total_fail + total_error

        self.stdout.write(f"  Uploads checked:  {total_checked}")
        self.stdout.write(self.style.SUCCESS(f"  Passed:           {total_pass}"))
        if total_fail:
            self.stdout.write(self.style.ERROR(f"  Failed:           {total_fail}"))
        else:
            self.stdout.write(f"  Failed:           {total_fail}")
        self.stdout.write(f"  Errors:           {total_error}")

        # DST breakdown
        pst_pass = sum(1 for r in all_results if r["la_dst"] == "PST" and r["fix_ok"] is True)
        pst_fail = sum(1 for r in all_results if r["la_dst"] == "PST" and r["fix_ok"] is False)
        pdt_pass = sum(1 for r in all_results if r["la_dst"] == "PDT" and r["fix_ok"] is True)
        pdt_fail = sum(1 for r in all_results if r["la_dst"] == "PDT" and r["fix_ok"] is False)
        near_dst_count = sum(1 for r in all_results if r["near_dst_transition"])

        self.stdout.write(f"\n  DST breakdown:")
        self.stdout.write(f"    PST period: {pst_pass} pass, {pst_fail} fail")
        self.stdout.write(f"    PDT period: {pdt_pass} pass, {pdt_fail} fail")
        self.stdout.write(f"    Near DST transition: {near_dst_count}")

        # Category breakdown with image counts
        category_stats = defaultdict(lambda: {"stations": 0, "images": 0, "uploads_pass": 0, "uploads_fail": 0})
        for station_id, summary in station_summaries.items():
            # Use the most common category for the station
            cats = summary["categories"]
            if len(cats) == 1:
                cat = cats.pop()
            elif len(cats) > 1:
                cat = f"MIXED:{','.join(sorted(cats))}"
            else:
                cat = "unknown"
            category_stats[cat]["stations"] += 1
            category_stats[cat]["images"] += summary["image_count"]
            category_stats[cat]["uploads_pass"] += summary["pass"]
            category_stats[cat]["uploads_fail"] += summary["fail"]

        self.stdout.write(f"\n  {'Category':<35} {'Stations':>8} {'Images':>8} {'Pass':>6} {'Fail':>6}")
        self.stdout.write(f"  {'-'*75}")
        for cat_key in sorted(category_stats.keys()):
            cs = category_stats[cat_key]
            self.stdout.write(
                f"  {cat_key:<35} {cs['stations']:>8} {cs['images']:>8} {cs['uploads_pass']:>6} {cs['uploads_fail']:>6}"
            )

        # Failing stations summary
        failing_stations = {k: v for k, v in station_summaries.items() if v["fail"] > 0}
        if failing_stations:
            self.stdout.write(self.style.ERROR(f"\n  FAILING STATIONS ({len(failing_stations)}):"))
            for station_id, summary in sorted(failing_stations.items()):
                self.stdout.write(
                    f"    {station_id:<20} {summary['image_count']:>6} images  "
                    f"{summary['fail']} upload(s) failed  offsets: {summary['offsets']}"
                )
        else:
            self.stdout.write(self.style.SUCCESS(f"\n  No failing stations!"))

        # Station offset map
        self.stdout.write(f"\n" + "=" * 120)
        self.stdout.write(self.style.MIGRATE_HEADING("STATION OFFSET MAP"))
        offset_map = {}
        for station_id, summary in sorted(station_summaries.items()):
            cats = summary["categories"]
            if not cats:
                offset_map[station_id] = None
                continue
            # Determine offset from categories
            hours_values = set()
            for cat in cats:
                if cat.startswith("clean:"):
                    h, _ = parse_exif_offset(cat.split(":", 1)[1])
                    hours_values.add(h)
                elif cat.startswith("corrupted:"):
                    hours_values.add(0)
            if len(hours_values) == 1:
                offset_map[station_id] = hours_values.pop()
            elif len(hours_values) > 1:
                offset_map[station_id] = f"MIXED:{hours_values}"
            else:
                offset_map[station_id] = None

        self.stdout.write(json.dumps(offset_map, indent=2, default=str))

        # Overall verdict
        self.stdout.write("")
        if total_fail == 0 and total_pass > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"ALL {total_pass} uploads verified successfully with per-station offset correction."
                )
            )
        elif total_fail > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"{total_pass}/{total_pass + total_fail} uploads verified. "
                    f"{total_fail} failures need investigation."
                )
            )

    # ──────────────────────────────────────────────────────────────
    # PER-STATION MODE (simpler, samples N images per station)
    # ──────────────────────────────────────────────────────────────
    def handle_per_station(self, *args, **options):
        samples_per_station = options["samples_per_station"]
        camera_station_filter = options["camera_station"]

        dbx = create_dropbox_client()
        if dbx is None:
            self.stderr.write(self.style.ERROR("Could not create Dropbox client."))
            return

        qs = Image.objects.filter(trigger_timestamp__isnull=False)
        if camera_station_filter:
            qs = qs.filter(upload__camera_station__station_id__icontains=camera_station_filter)

        station_counts = (
            qs.values("upload__camera_station__station_id")
            .annotate(image_count=Count("id"))
            .order_by("upload__camera_station__station_id")
        )

        total_stations = len(station_counts)
        self.stdout.write(f"Found {total_stations} camera stations.\n")

        for idx, station_info in enumerate(station_counts, 1):
            station_id = station_info["upload__camera_station__station_id"]
            image_count = station_info["image_count"]

            station_images = qs.filter(upload__camera_station__station_id=station_id).order_by("trigger_timestamp")
            count = station_images.count()

            sample_indices = []
            if count <= samples_per_station:
                sample_indices = list(range(count))
            else:
                step = max(1, (count - 1) // (samples_per_station - 1))
                sample_indices = list(range(0, count, step))[:samples_per_station]

            self.stdout.write(f"[{idx}/{total_stations}] Station: {station_id} ({image_count} images)")

            for si in sample_indices:
                image = station_images[si]
                exif = read_exif_from_dropbox(dbx, image.dropbox_file_path)
                result = verify_fix(image, exif)

                offset_str = result["exif_offset_raw"] or "N/A"
                cat_str = result["offset_category"] or "?"

                if result["error"]:
                    status = self.style.WARNING(f"ERR: {result['error'][:50]}")
                elif result["fix_ok"]:
                    status = self.style.SUCCESS("OK")
                elif result["fix_ok"] is False:
                    status = self.style.ERROR(f"WRONG by {result['fix_error_hours']:+.1f}h")
                else:
                    status = "?"

                self.stdout.write(f"    EXIF: {result['exif_datetime']}  Offset: {offset_str}  Cat: {cat_str}  Fix: {status}")

    # ──────────────────────────────────────────────────────────────
    # DEFAULT MODE (random sample across dataset)
    # ──────────────────────────────────────────────────────────────
    def handle_random_sample(self, *args, **options):
        sample_size = options["sample_size"]
        camera_station = options["camera_station"]

        dbx = create_dropbox_client()
        if dbx is None:
            self.stderr.write(self.style.ERROR("Could not create Dropbox client."))
            return

        qs = Image.objects.filter(trigger_timestamp__isnull=False)
        if camera_station:
            qs = qs.filter(upload__camera_station__station_id__icontains=camera_station)

        total = qs.count()
        self.stdout.write(f"Found {total} images. Sampling {min(sample_size, total)}.\n")

        if total == 0:
            return

        step = max(1, total // sample_size)
        for i, idx in enumerate(range(0, total, step)):
            if i >= sample_size:
                break
            image = qs[idx]
            exif = read_exif_from_dropbox(dbx, image.dropbox_file_path)
            result = verify_fix(image, exif)

            status = "?"
            if result["error"]:
                status = f"ERR: {result['error'][:50]}"
            elif result["fix_ok"]:
                status = "OK"
            elif result["fix_ok"] is False:
                status = f"WRONG by {result['fix_error_hours']:+.1f}h"

            self.stdout.write(
                f"  [{i+1:>3}] {result['exif_datetime']}  "
                f"Offset: {result['exif_offset_raw']}  "
                f"DST: {result['la_dst']}  Fix: {status}"
            )
