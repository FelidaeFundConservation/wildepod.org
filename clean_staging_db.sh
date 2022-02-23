#!/bin/zsh
find -name "000*.py" -delete
python manage.py makemigrations --settings=config.settings.staging
python manage.py migrate --settings=config.settings.staging
export DJANGO_SUPERUSER_USERNAME="test"
export DJANGO_SUPERUSER_PASSWORD="test1234"
python manage.py createsuperuser --noinput --email test@test.com --settings=config.settings.staging
python manage.py shell --settings=config.settings.staging < scratch/load.py
python manage.py collectstatic --noinput --clear --settings=config.settings.staging
python manage.py runserver --settings=config.settings.staging
