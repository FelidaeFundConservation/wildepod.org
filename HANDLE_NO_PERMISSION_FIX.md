# `handle_no_permission` Compatibility Fix

## Problem

Views using both `LoginRequiredMixin` and `braces.StaffuserRequiredMixin` would raise a `TypeError` when a non-staff user accessed them, causing a **500 error** in production instead of a clean redirect or 403.

**Root cause:** `braces.StaffuserRequiredMixin` calls `handle_no_permission(request)`, passing `request` as a positional argument. Django's `AccessMixin.handle_no_permission(self)` does not accept a `request` parameter, so the call fails.

## Fix

Each affected view class gets this override:

```python
def handle_no_permission(self, request=None):
    from django.contrib.auth.mixins import AccessMixin
    return AccessMixin.handle_no_permission(self)
```

This accepts the `request` argument from `braces` (and ignores it), then delegates to Django's implementation, which correctly redirects unauthenticated users to login or raises `PermissionDenied` (403) for authenticated non-staff users.

## Affected Views

### `siteapps/images/views/search_images.py`
- `SearchImagesView` — fixed previously (reference implementation)

### `siteapps/images/views/upload.py`
- `FixUploadSetsView`
- `ModifyUploadSetImagesView`

### `siteapps/explore/views/snapshot.py`
- `SnapshotCreateView`
- `SnapshotListView`

### `siteapps/explore/views/query_data.py`
- `SearchDataView`

### `siteapps/explore/views/set_priority.py`
- `PriorityView`
- `ConfirmUpdateView`

### `siteapps/explore/views/megadetector.py`
- `ExploreMegadetectorView`

### `siteapps/explore/views/track_volunteer_engagement.py`
- `TrackVolunteerEngagementView`

## Production Impact

| User type | Before fix | After fix |
|---|---|---|
| Anonymous user | 500 TypeError | Redirect to login |
| Authenticated non-staff | 500 TypeError | 403 Forbidden |
| Staff user | Works normally | Works normally (unchanged) |

## Tests Updated

Test files that had `try/except TypeError` workarounds were updated to assert the correct status codes (`302` or `403`) instead:

- `siteapps/explore/tests/test_views_query_data.py`
- `siteapps/explore/tests/test_views_set_priority.py`
- `siteapps/explore/tests/test_views_snapshot.py`
- `siteapps/explore/tests/test_views_track_volunteer_engagement.py`

All 69 tests pass after the fix.
