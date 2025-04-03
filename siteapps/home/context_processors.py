from django.conf import settings


def global_settings(request):
    return {
        # Add your context variables here
        'is_prod': 'prod' in settings.WSGI_APPLICATION,
        'is_staging': 'staging' in settings.WSGI_APPLICATION,
        'is_bhutan': 'bhutan' in settings.WSGI_APPLICATION,
    }
