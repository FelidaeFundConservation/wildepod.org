#!/bin/zsh
rm -rf db.sqlite3
find -name "000*.py" -delete
python manage.py makemigrations --settings=config.settings.local
python manage.py migrate --settings=config.settings.local
export DJANGO_SUPERUSER_PASSWORD="test123"
python manage.py createsuperuser --noinput --email abhaykash12@gmail.com --name abhay --settings=config.settings.local
python manage.py shell --settings=config.settings.local < scratch/load.py
python manage.py runserver --settings=config.settings.local
