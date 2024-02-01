# Django Website for WildePod (Felidae Conservation Fund)


## Quick Setup
#Setting up the environment for the first time

1. Git clone this repo
2. Create a virtualenv
3. Install Python dependencies `pip install -r requirements.txt`
4. Install SASS compiler - Sass is a stylesheet language that’s compiled to CSS. It is installed on the OS level, not in the virtualenv.
   * https://sass-lang.com/install
   * If you're using MacOs/Linux , you can use Homebrew : `brew install sass/sass/sass`
   Install Homebrew package manager if you still don't have (https://brew.sh)
5. Set env variables:
    * Set the Google Cloud project : `export GOOGLE_CLOUD_PROJECT=wildepod-339517`
    * `export PYTHONPATH=<your_project_path>`
6. By default Django uses a sqlite database locally. Verify this by checking DATABASES variable in: `/config/settings/local.py`

#Run the Django server locally for the first time

1. Make migrations - `python manage.py makemigrations --settings=config.settings.local`
   (Note: This may not work since `migrations` folder is gitignored for now and Django requires the folder's existence.
   To fix that for now, simply create python packages named `migrations` in each of the app packages.
   This has to be a package so the `migrations` folder must have a `__init__.py` file or django can't see it.
2. Apply migrations - `python manage.py migrate --settings=config.settings.local`
   These two commands check and update the DB models as necessary for our Django project. The very first time you run it, it will create all the DB models. Afterwords, it will only do the required updates. Do not run this command on Staging or Prod unless you're sure of what you're doing.
3. Create superuser - `python manage.py createsuperuser --settings=config.settings.local`
4. Run server - `python manage.py runserver --settings=config.settings.local`

This should have things running on `localhost:8000` and use a local sqlite db

# Initalize some data - hacky version (Might be outdated)

1. Download the "active camera data" & "Camera inventory" sheets from the Slack channel
2. Alter lines 7-10 of `scratch/load.py` file accordingly depending on where the downloaded files are saved
3. Run `python manage.py shell --settings=config.settings.local < scratch/load.py`

This should be fine for those spreadsheets. If there is any error, add that row to the skip list in the code

## Local development environment
To have a fully operational environment for development, you need to have access to the project's GCP.

### Google Cloud SDK

1. You should have Google Cloud SDK installed (https://cloud.google.com/sdk/docs/install)
2. Ask for your credentials on Goggle Cloud, to the WildePod adminstrators.
3. You have to be logged in order to proceed to the next steps

    gcloud auth application-default <e-mail login>
    gcloud auth <e-mail login>
    gcloud config set project <project-id>
    * Maybe there is some unknow issue here with secret-key.


### Run Django project

1. You need configuration files to access database.
2. Run `python manage.py runserver --settings=config.settings.dev`

This should have things running on `localhost:8000` and use the project database.



---

## With Gcloud

1. Read the tutorial [here](https://cloud.google.com/python/django/appengine).
2. Alter `app.yaml` & `dev/staging/prod` settings as needed
3. Deploy + Check cloud build to see what happpened

---
## Deployment instructions
To deploy to GCP on existing environments (test, staging and prod)

Ask for the following files:
* /env_file.yaml
* /env_file.py
* /cnfig/settings/env_file.py
* /config/wsgi/env_file.py

Deploy app using `gcloud app deploy env_file.yaml`

---
## With SQL proxy

Setenv

```
export USE_CLOUD_SQL_AUTH_PROXY=true
export GOOGLE_CLOUD_PROJECT=<project-name>
```

Emulating google app.yaml locally. Make sure proxy is running using

`./cloud_sql_proxy -instances="<project-name>:<region>:<dbname>"=tcp:<port>`

Then run this so app.yaml uses the proxy. Note there can be many .yaml configs that can be specified

`dev_appserver.py app.yaml --env_var=USE_CLOUD_SQL_AUTH_PROXY=true`

---

## Gotchas

- If uploading to buckets when running locally fails, this is likely due to missing credentials. This can be fixed by running

```
gcloud auth application-default login
```

in addition to regular auth

```
gcloud auth login
```

Be sure to set the project id as well

```
gcloud config set project <project-id>
```

- Currently there are issues with getting the `id_token` directly from the metadata server and it is unclear why.
  So for local developement, a workaround is to set the identity token as an env and then use that as the
  authorization header. Specifically, run this (after setting the application default login).

```
export ID_TOKEN="$(gcloud auth print-identity-token -q)"
```

Check if you are connected to the project's GCP

```
gcloud auth list
```
---


## Deployment instructions (Fresh GCP - if needed)

1. Create a new GCP project
2. Enable cloud function API & deploy megadetector cloud function (independent of app engine)
3. Create CloudSQL instance & prod/staging databases
4. Create relevant buckets on Google Storage and make sure they have fine-grained permissions
5. Create relevant Dropbox apps with appropriate permissions & set tokens in env if haven't already
6. Use cloud sql proxy and run db migrations
7. Install sass compiler (if needed) and run from project root. This should continuously watch for changes in scss files and compile them to css (static files are served using whitenoise)
   `sass --watch --style compressed ./siteapps/static/scss/main.scss:./siteapps/static/css/main.css`
8. Collect static files using `python manage.py collectstatic --settings=config.settings.prod`
9. Deploy app using `gcloud app deploy`
10. Add relevant secrets from .env to Secret manager (Important: Give your appengine app "Secret Manager Secret Accessor" permission)
