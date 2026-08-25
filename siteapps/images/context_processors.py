# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from images.models import ImageQueue


def expert_assignment(request):
    """How many assigned images an expert has left, for the nav's "Assigned to me" link.

    Bulk assignment appends to the expert's ImageQueue and tells them nothing, and the only
    link to the searched queue anywhere is on the staff search page -- so today an expert's
    work reaches them by somebody sending them a URL. This is the stopgap until assignment
    surfaces in the tab bar; when it becomes a field of its own, read that instead.

    Zero renders no nav item rather than an empty one. With no queue assigned the searched
    flow falls through to ordinary volunteer images, so a link on an empty queue would promise
    assigned work and quietly serve something else.
    """
    user = getattr(request, "user", None)

    if not (user and user.is_authenticated and user.is_expert):
        return {}

    # image_order is what separates a queue somebody built from one the system handed out:
    # annotating anything assigns an automatically precomputed queue, and those have no order.
    # Counting them would put a number in the nav that nobody asked for.
    assigned = ImageQueue.objects.filter(assigned_to__human=user).exclude(image_order=[])

    return {
        "assigned_image_count": sum(
            max(len(queue.image_order) - queue.position, 0) for queue in assigned
        )
    }
