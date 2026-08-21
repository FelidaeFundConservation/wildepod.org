# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import datetime


def get_filter_params(
    start_date,
    end_date,
    macrosite_name,
    camera_id,
    staff_review_needed=None,
    image_reported=None,
    flag_reason=None,
    flag_source=None,
):
    """Builds a kwargs dict of Image filters for the annotation queues.

    Arguments
    ---
        - flag_reason (str | None): Narrows a staff review queue to one reason, so reviewers
          can work through (say) only "possible human" flags. Ignored unless
          staff_review_needed is set, and ignored if it is not a recognised reason.
        - flag_source (str | None): Narrows a staff review queue to deliberate or automatic
          flags. Same rules as flag_reason. See MANUAL handling below for why blanks count
          as deliberate.
    """
    filters = {}

    if start_date and start_date != "None":
        start_date = datetime.datetime.fromisoformat(str(start_date))
        filters["trigger_timestamp__gte"] = start_date

    if end_date and end_date != "None":
        end_date = (
            datetime.datetime.fromisoformat(str(end_date)) + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)
        )
        filters["trigger_timestamp__lte"] = end_date

    if macrosite_name:
        filters["upload__camera_station__micro_site__macro_site__name"] = macrosite_name

    if camera_id and camera_id != "None":
        filters["upload__camera_station__station_id"] = camera_id

    if staff_review_needed:
        filters["staff_review_needed"] = True

        # Imported here rather than at module scope to keep this module free of model imports
        from images.models.image import StaffReviewFlagReason, StaffReviewFlagSource

        if flag_reason in StaffReviewFlagReason.values:
            filters["flag_reason"] = flag_reason

        if flag_source == StaffReviewFlagSource.MANUAL:
            # Images flagged before provenance was recorded have a blank source. Treat them as
            # deliberate so the queue does not silently empty out the day this ships -- an
            # unattributable flag is more likely to be someone's request than an auto-flag.
            filters["flag_source__in"] = [StaffReviewFlagSource.MANUAL, ""]
        elif flag_source in StaffReviewFlagSource.values:
            filters["flag_source"] = flag_source

    if image_reported:
        filters["image_reported"] = True

    return filters
