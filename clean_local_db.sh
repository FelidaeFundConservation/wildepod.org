#!/bin/zsh
# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

rm -rf db.sqlite3
python manage.py makemigrations --settings=config.settings.local
python manage.py migrate --settings=config.settings.local
python manage.py shell --settings=config.settings.local < scratch/load.py
export DJANGO_SUPERUSER_PASSWORD="test123"
python manage.py createsuperuser --noinput --email test@test.com --name test --settings=config.settings.local
python manage.py runserver --settings=config.settings.local
