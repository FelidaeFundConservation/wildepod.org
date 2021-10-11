# Utility functions for uploads. This is mainly wrappers around external APIs
import json

from django.conf import settings
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials


# TODO: This is temporary since credentials.json isn't required when this runs on gcloud
# This code needs to be changed to use credentials.json only if running locally
class GdriveClient:
    def __init__(self):
        scopes = ["https://www.googleapis.com/auth/drive"]
        file = "credentials.json"
        creds = ServiceAccountCredentials.from_json_keyfile_name(file, scopes)
        self.service = build("drive", "v3", credentials=creds)

    def create_folder(self, name):
        # https://drive.google.com/drive/folders/{parent}
        # TODO: Change the parent folder key from here and move it to the env
        body = {
            "parents": [settings.GDRIVE_SHARED_FOLDER_ID],
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        fields = "parents,id"
        folder = self.service.files().create(body=body, fields=fields).execute()
        folder_id = folder.get("id")
        return f"https://drive.google.com/drive/folders/{folder_id}"
