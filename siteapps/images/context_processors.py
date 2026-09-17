# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging

from images.models.upload import Upload


def pending_uploads(request):
    """
    Expose the signed-in user's own unfinalized uploads to the nav bar.

    Deliberately scoped to `volunteer=user` even for staff. The uploads list
    page shows staff every user's pending upload, but the nav badge is a
    personal to-do: a staff member should not be nagged about work that is not
    theirs to finish.

    Runs on every page, so it stays a single indexed COUNT plus one row fetch
    when there is exactly one. Nothing here is written back to the database.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_active:
        return {}

    # This runs on every page, and 500.html extends _base.html — so an exception
    # here turns any database-level failure into a broken error page as well as a
    # broken request. A nav decoration is never worth that: log it and render the
    # bar without the badge.
    try:
        pending = Upload.objects.filter(volunteer=user, upload_complete=False, deleted=False)
        count = pending.count()
        if not count:
            return {"nav_pending_upload_count": 0}

        return {
            "nav_pending_upload_count": count,
            # Only used to deep-link the single-upload case straight to Finalize.
            "nav_pending_upload": pending.order_by("-created").first() if count == 1 else None,
        }
    except Exception:
        logging.exception("Could not count pending uploads for the nav bar")
        return {"nav_pending_upload_count": 0}
