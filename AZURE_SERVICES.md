# Azure Services Audit

## Summary

**WildePod does not use any Microsoft Azure services.**

A full audit of the codebase (Python source, configuration files, deployment scripts, CI/CD workflows, and documentation) found zero references to Azure or any Microsoft cloud product.

## Cloud Provider in Use

WildePod runs entirely on **Google Cloud Platform (GCP)**. The GCP services used are:

| Service | GCP Product | Purpose |
|---------|------------|---------|
| Object / media storage | Google Cloud Storage (GCS) | Storing camera-trap images and other media files |
| Relational database | Cloud SQL (PostgreSQL) | Primary application database |
| Secret management | Secret Manager | Storing credentials and API keys |
| Async task queuing | Cloud Tasks | Background processing jobs |
| Structured logging | Cloud Logging | Application and request logging |
| App hosting | App Engine (standard / flexible) | Serving the Django application |
| Serverless inference | Cloud Functions | YOLOv5 species-detection model endpoint |
| NoSQL / metadata | Cloud Datastore | Additional metadata storage |

## Python Dependencies (GCP)

The following GCP-specific packages are declared in `pyproject.toml`:

- `django-storages[google]` — GCS media-file backend for Django
- `google-api-python-client` — Core GCP API client
- `google-auth`, `google-auth-httplib2`, `google-auth-oauthlib` — GCP authentication
- `google-cloud-datastore` — Cloud Datastore client
- `google-cloud-secret-manager` — Secret Manager client
- `google-cloud-logging` — Cloud Logging client
- `google-cloud-tasks` — Cloud Tasks client

## Conclusion

No Azure migration or Azure-specific configuration is needed. If Azure services are introduced in the future this document should be updated accordingly.
