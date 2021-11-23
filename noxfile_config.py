TEST_CONFIG_OVERRIDE = {
    "ignored_versions": ["2.7"],
    "gcloud_project_env": "GOOGLE_CLOUD_PROJECT",
    # 'gcloud_project_env': 'BUILD_SPECIFIC_GCLOUD_PROJECT',
    # A dictionary you want to inject into your test. Don't put any
    # secrets here. These values will override predefined values.
    "envs": {"DJANGO_SETTINGS_MODULE": "config.settings.prod"},
}
