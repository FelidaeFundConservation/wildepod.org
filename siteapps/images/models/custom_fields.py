import datetime


def get_filter_params(start_date, end_date, macrosite_name, camera_id, staff_review_needed=None):
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

    return filters
