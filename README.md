# Django Website for WildePod (Felidae Conservation Fund)

## Table of Contents
- [Quick Setup](#quick-setup)
  - [Setting up the environment for the first time](#setting-up-the-environment-for-the-first-time)
  - [Strictly Local: Run the Django server locally for the first time](#strictly-local-run-the-django-server-locally-for-the-first-time)
    - [Initialize some data - hacky version (Might be outdated)](#initalize-some-data---hacky-version-might-be-outdated)
  - [Local with Cloud: Local development environment with GCloud connectivity](#local-with-cloud-local-development-environment-with-gcloud-connectivity)
- [Gotchas](#gotchas)
- [Deployment instructions (Fresh GCP)](#deployment-instructions-fresh-gcp)
- [Deploying new YOLOv5 species detection model](#deploying-new-yolov5-species-detection-model)
- [System Overview Flowcharts](#system-overview-flowcharts)
  - [Image Queue System](#image-queue-system)
  - [Image Data Loading](#image-data-loading)
  - [Save Image/Annotations](#save-imageannotations)
  - [Upload Processing](#upload-processing)

---

## Quick Setup
### Setting up the environment for the first time

1. Git clone this repo
2. Install uv (modern Python package manager):
   * macOS/Linux: 
   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   * Or via Homebrew:
   ```
   brew install uv
   ```
   * Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
   * More info: https://docs.astral.sh/uv/getting-started/installation/
3. Install dependencies:
   ```
   uv sync
   ```
   This single command will:
   - Create a virtual environment (`.venv`) with Python 3.10
   - Install all dependencies from `pyproject.toml`
   - Verify or update the lock file (`uv.lock`) for reproducible builds
4. Install SASS compiler - Sass is a stylesheet language that's compiled to CSS. It is installed on the OS level, not in the virtualenv.
   * https://sass-lang.com/install
   * If you're using MacOs/Linux , you can use Homebrew : 
   ```
   brew install sass/sass/sass
   ```

---

### Now you have a choice,
* **Strictly Local :**    Run a bare-bones Django server locally connecting to a local database: `config.settings.local`  
    
  This lets you work with a local SQLite (or even PostgreSQL) database but will not let you access the annotation images, dropbox uploads, cloud tasks, model processing etc. This is still useful for quick testing and also experimenting in a completely sandboxed, local environment.        


* **Local with Cloud :**  Run the Django server locally but connect to Wildepod cloud services: `config.settings.staging`

  This lets you run the server locally but connect to all our cloud resources. This is a useful option for debugging and feature development but you'll have to be mindful since you can even directly work with / modify prod data.
    
---

### Strictly Local: Run the Django server locally for the first time
1. By default Django uses a sqlite database locally. Verify this by checking DATABASES variable in: `/config/settings/local.py`

2. Make migrations 
```
uv run manage.py makemigrations --settings=config.settings.local
```
   (Note: This may not work since `migrations` folder is gitignored for now and Django requires the folder's existence.
   To fix that for now, simply create python packages named `migrations` in each of the app packages.
   This has to be a package so the `migrations` folder must have a `__init__.py` file or django can't see it.)

3. Apply migrations 
```
uv run manage.py migrate --settings=config.settings.local
```
   These two commands check and update the DB models as necessary for our Django project. The very first time you run it, it will create all the DB models. Afterwords, it will only do the required updates. Do not run this command on Staging or Prod unless you're sure of what you're doing.

4. Create superuser
```
uv run manage.py createsuperuser --settings=config.settings.local
```

5. Run server
```
uv run manage.py runserver --settings=config.settings.local
```

This should have things running on `localhost:8000` and use a local sqlite db

#### Initalize some data - hacky version (Might be outdated)

1. Download the "active camera data" & "Camera inventory" sheets from the Slack channel
2. Alter lines 7-10 of `scratch/load.py` file accordingly depending on where the downloaded files are saved
3. Run Django shell script to import data
```
uv run manage.py shell --settings=config.settings.local < scratch/load.py
```
This should be fine for those spreadsheets. If there is any error, add that row to the skip list in the code

---

### Local with Cloud: Local development environment with GCloud connectivity
To have a fully operational environment for development, you need to have access to the project's GCP. We use a number of cloud services (Cloud SQL, Image storage, Secrets manager etc). You need to be authenticated to access these.

1. If not provided already, ask the WildePod adminstrators to add your credentials to GCP. 
2. Install the GCloud command line SDK (https://cloud.google.com/sdk/docs/install)
3. Authenticate yourself with GCloud and set the config.
```
gcloud auth application-default login
gcloud auth login
gcloud config set project wildepod-339517
```
4. Set the following environment variables

    * Set the Google Cloud project : 
    ```
    export GOOGLE_CLOUD_PROJECT=wildepod-339517
    ```
    * Use Cloud SQL Auth proxy for connecting to cloud dbs : 
    ```
    export USE_CLOUD_SQL_AUTH_PROXY=True
    ```
    * Disable HTTPS redirecting when accessing sites locally : 
    ```
    export DJANGO_SECURE_SSL_REDIRECT=False
    ```
        - Local dev servers won't have HTTPS. However, both Django and Chrome may try to redirect your request to HTTPS which will result in an error.
        - In Chrome, you'll have to disable HSTS for a Local Domain and clear any cached settings for localhost.

5. Install and launch [Cloud SQL Proxy](https://docs.cloud.google.com/sql/docs/postgres/sql-proxy)
```
./cloud-sql-proxy -p 5440 wildepod-339517:us-west2:wildepoddb
```
6. In another terminal, run the local server with staging config
```
uv run manage.py runserver --settings=config.settings.staging
```

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


## Deployment instructions (Fresh GCP)
Jump ahead to step 8 if deploying on existing existing environments (staging, prod, bhutan). If you're not familiar with AppEngine, please go through [this tutorial](https://cloud.google.com/python/django/appengine) first.


1. Create a new GCP project
2. Enable cloud function API & deploy megadetector cloud function (independent of app engine)
3. Create CloudSQL instance & prod/staging databases
4. Create relevant buckets on Google Storage and make sure they have fine-grained permissions
5. Create relevant Dropbox apps with appropriate permissions & set tokens in env if haven't already
6. Use cloud sql proxy and run db migrations
7. Add relevant secrets from .env to Secret manager (Important: Give your appengine app "Secret Manager Secret Accessor" permission)
8. Install sass compiler (if needed) and run from project root. This should continuously watch for changes in scss files and compile them to css (static files are served using whitenoise)
   `sass --watch --style compressed ./siteapps/static/scss/main.scss:./siteapps/static/css/main.css`
9. Collect static files using `python manage.py collectstatic --settings=config.settings.prod`
10. Deploy app using `gcloud app deploy <env>.yaml`


---
## Deploying new YOLOv5 species detection model
1. Put the trained .pt file in the same directory with a function source file "main.py" ([see here](https://github.com/FelidaeFundConservation/wildepod.org/pull/240#issue-2080609231)) and a requirements.txt.
```
requirements.txt
----------------------------------
yolov5==7.0.13
functions-framework==3.5.0
dill==0.3.7
Pillow==9.0.1
```
2. In main.py, ensure you've replaced the file in `yolov5.load(FILE_NAME)` with the name of the new .pt file.
3. Compress the files into an archive (.zip).
4. In the GCloud console products sidebar, navigate to `Serviceless < Cloud Functions`, and click the name of the species detector function.
5.  On the function details page, click "Edit".
6.  Leave the 'Configuration' page as is unless it's necessary to modify. Click "Next".
7.  On the Code page under the Source Code dropdown, select "Zip Upload".
8.  Select the destination bucket to the one currently in use by the function. This should be `gcf-v2-sources-... < wildepod-species-detector-...`. You can determine this if there's already a function-source.zip in the folder.
9.  Upload the new zip file, then click Deploy.

(For a new 2nd gen cloud function, steps should be the same, albeit with some additional setup.)

Note: The build may take awhile, so the console may show an error temporarily if it doesn't complete within a certain time. This should clear once the build completes. If the error persists after 20 or so minutes, there's likely an actual error, and you should check the logs to troubleshoot.

---
# System Overview Flowcharts

### Image Queue System

This figure visualizes how images are gathered and shown to the annotators.

![WildepodQueueLogic](https://github.com/FelidaeFundConservation/wildepod.org/assets/78624502/0b860b23-459c-4586-9af4-7b490b0a126a)
---
### Image Data Loading

This figure visualizes what data is calculated and retrieved from an image-to-be-annotated. 

![WildepodLoadImage](https://github.com/FelidaeFundConservation/wildepod.org/assets/78624502/377f10a0-a711-4a1f-9c80-f6cb098b6b8d)
---
### Save Image/Annotations

This figure visualizes the process of saving and updating image annotations.

![WildepodSaveAnnotations](https://github.com/FelidaeFundConservation/wildepod.org/assets/78624502/4ad75091-5e05-46e7-8feb-8707afc14524)
---
### Upload Processing

This figure visualizes how user upload sets are created and processed.

![WildepodImageUpload drawio](https://github.com/FelidaeFundConservation/wildepod.org/assets/78624502/ef0bf6e4-8647-4990-96ab-28c76c4fca69)

