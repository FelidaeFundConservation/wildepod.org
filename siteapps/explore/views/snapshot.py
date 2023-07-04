import datetime as dt
import json
import logging

from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import File as DjangoFile
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect
from django.urls import reverse
from django.urls.base import reverse_lazy
from django.views.generic import FormView, ListView, View
from explore.forms import CreateSnapshotForm
from explore.models import Snapshot
from exports.views import start_export
from google.cloud import tasks_v2

MAX_VOTES_PER_IMAGE = 3


class SnapshotCreateView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "explore/snapshots/create.html"
    form_class = CreateSnapshotForm
    success_url = reverse_lazy("explore:data_snapshots")

    def post(self, request, *args, **kwargs):
        form = CreateSnapshotForm(request.POST)

        if form.is_valid():
            # Create a client.
            client = tasks_v2.CloudTasksClient()

            # TODO(developer): Uncomment these lines and replace with your values.
            project = settings.GCP_PROJECT_ID
            queue = settings.EXPORT_QUEUE_NAME
            location = settings.GCP_REGION

            # Construct the fully qualified queue name.
            parent = client.queue_path(project, location, queue)

            payload = {"user": self.request.user.pk}
            start_date = form.cleaned_data["start_date"]
            if start_date:
                payload["start_date"] = start_date.strftime(settings.EXPORT_DATE_FORMAT)
            end_date = form.cleaned_data["end_date"]
            if end_date:
                payload["end_date"] = end_date.strftime(settings.EXPORT_DATE_FORMAT)
            macrosites = form.cleaned_data["macrosites"]
            if macrosites:
                payload["macrosites"] = []
                for site in macrosites:
                    payload["macrosites"].append(site.pk)

            start_export(payload)
            # payload_json = json.dumps(payload, cls=DjangoJSONEncoder)


            # The API expects a payload of type bytes.
            # converted_payload = payload_json.encode()

            # # Construct the request body.
            # task = {
            #     "app_engine_http_request": {  # Specify the type of request.
            #         "http_method": tasks_v2.HttpMethod.POST,
            #         "relative_uri": f"/exports/start/{settings.EXPORT_URL_SUFFIX}/",
            #         "app_engine_routing": {
            #             "service": settings.EXPORT_SERVICE_NAME,
            #         },
            #         "headers": {
            #             "Content-Type": "application/json",
            #         },
            #         "body": converted_payload,
            #     }
            # }

            # logging.info(f"Task details {task}")

            # # Use the client to build and send the task.
            # response = client.create_task(parent=parent, task=task)
            # logging.info("Created task {}".format(response.name))

        return redirect("explore:data_snapshots")


class SnapshotListView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    template_name = "explore/snapshots/list.html"
    model = Snapshot
