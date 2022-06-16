#!/bin/zsh
python manage.py makemigrations --settings=config.settings.staging
python manage.py migrate --settings=config.settings.staging
python manage.py shell --settings=config.settings.staging < scratch/load.py
python manage.py collectstatic --noinput --clear --settings=config.settings.staging
