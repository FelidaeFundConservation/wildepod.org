# Django Website for WildePod (Felidae Conservation Fund)

---

## Local dev

Setup

1. Git clone this repo
2. Create a virtualenv `python -m venv <your_virtualenv_name>`
3. Activate the local virtualenv.
4. `pip install -r requirements.txt`
5. Rename `.example_env` to `.env`
6. Run `./clean_local_db.sd`

This should have things running on `localhost:8000` and use a local sqlite db

### Initalize some data - hacky version

1. Download the "active camera data" & "Camera inventory" sheets from the Slack channel
2. Alter lines 7-10 of `scratch/load.py` file accordingly depending on where the downloaded files are saved
3. Run `python manage.py shell --settings=config.settings.local < scratch/load.py`

This should be fine for those spreadsheets. If there is any error, add that row to the skip list in the code

---

## With Gcloud

1. Read the tutorial [here](https://cloud.google.com/python/django/appengine).
2. Alter `app.yaml` & `dev/staging/prod` settings as needed
3. Deploy + Check cloud build to see what happpened

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
