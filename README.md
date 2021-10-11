# Django Website for Felidae

---

## Local dev

Setup
1. Git clone this repo
2. Create a virtualenv
3. `pip install -r requirements.txt`
4. Create a local file called `.env` at the root of this repo.
5. Go to GCloud secrets manager, copy the latest secrets & paste it into this `.env` file

Initialize django project
1. Make migrations - `python manage.py makemigrations --settings=config.settings.local`
(Note: This may not work since `migrations` folder is gitignored for now and Django requires the folder's existence.
To fix that for now, simply create python packages named `migrations` in each of the app packages.
This has to be a package so the `migrations` folder must have a `__init__.py` file or django can't see it.
2. Apply migrations - `python manage.py migrate --settings=config.settings.local`
3. Create superuser - `python manage.py createsuperuser --settings=config.settings.local`
4. Run server - `python manage.py runserver --settings=config.settings.local`

This should have things running on `localhost:8000` and use a local sqlite db

### Initalize some data - hacky version
1. Download the "active camera data" & "Camera inventory" sheets from the metadata collection spreadsheet
2. Alter lines 7-10 of `scratch/load.py` file accordingly depending on where the downloaded files are saved
3. Run `python manage.py shell --settings=config.settings.local < scratch/load.py`

This should be fine for those spreadsheets. If there is any error, add that row to the skip list in the code

---

## With Gcloud

1. Read the tutorial [here](https://cloud.google.com/python/django/appengine).
2. Alter `app.yaml` & `dev/staging/prod` settings as needed
3. Deploy + Check cloud build to see what happpened
