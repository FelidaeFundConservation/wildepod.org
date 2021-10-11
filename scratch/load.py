# Run using python manage.py shell --settings=config.settings.local < scratch/load.py
from datetime import datetime

import pandas as pd
from inventory.models import Camera, CameraBrand, CameraModel, Padlock, PythonLock
from locations.models import Area, CameraTrap, County, Grid, HabitatType, MacroSite, MicroSite, TrailType
from uploads.models import CameraTrapAction, UploadError, UploadErrorEffect

# Download active camera data sheet as tsv into the local_data folder and rename as necessary
active_cameras_df = pd.read_csv("local_data/active_cameras.tsv", delimiter="\t")
# Download camera inventory data sheet as tsv into the local_data folder and rename as necessary
camera_inventory_df = pd.read_csv("local_data/camera_inventory.tsv", delimiter="\t")

camera_inventory_df = camera_inventory_df.fillna("")
active_cameras_df = active_cameras_df.fillna("")

# Load camera inventory
for i, rec in camera_inventory_df.iterrows():
    if not rec["Serial #"].strip():
        continue
    print(f'(Row - {i}) Loading Camera with Serial number - {rec["Serial #"]}')
    brand, _ = CameraBrand.objects.get_or_create(name=rec["Brand"].strip())
    power_source = "solar" if rec["# of batteries"].lower() == "solar" else "battery"
    num_batteries = rec["# of batteries"].lower() if rec["# of batteries"].lower() != "solar" else 0
    num_batteries = None if num_batteries == "" else num_batteries

    if not CameraModel.objects.filter(number=rec["Model #"]).exists():
        model, _ = CameraModel.objects.get_or_create(
            number=rec["Model #"],
            name=rec["Camera model"],
            power_source=power_source,
            num_batteries=num_batteries,
            brand=brand,
        )
    else:
        model = CameraModel.objects.get(number=rec["Model #"])

    status = None
    if rec["Comments"] == "Ready to deploy":
        status = "ready_to_deploy"
    elif rec["Comments"] == "Deployed":
        status = "deployed"
    elif rec["Comments"] == "Stolen":
        status = "stolen"
    elif rec["Comments"] == "To be refurbished":
        status = "needs_refurbishment"
    # One entry has a missing status & must be fixed in the spreadsheet
    if not status:
        continue
    if not Camera.objects.filter(serial_number=rec["Serial #"]).exists():
        camera, _ = Camera.objects.get_or_create(
            serial_number=rec["Serial #"].strip(),
            model=model,
            status=status,
            comments=rec["Reason camera needs to be refurbished"],
        )
        print(f'Successfully created record for camera with serial number - {rec["Serial #"]}')

# Load active camera traps
for i, rec in active_cameras_df.iterrows():
    camera_trap_id = rec["Unnamed: 0"]
    print(f"(Row - {i}) Loading Camera trap with id - {camera_trap_id}")
    if not camera_trap_id or not rec["Latitude"] or not rec["Longitude"]:
        print("Missing camera trap id or lat/long. Skipping...")
        continue
    # These are offending camera IDs that don't quite fit the existing schema.
    if camera_trap_id in [
        "LAH13Bsnare2",
        "DIA01A",
        "DIA02A",
        "DIA03A",
        "DIA04A",
        "DIA05A",
        "DIA06A",
        "DIA07A",
        "DIA08A",
        "DIA09A",
        "DIA10A",
        "OLM03A",
        "PLT01A",
        "PUC05A",
        "PUC05A3",
        "PUC09B",
        "PUC09B2",
        "RPP01B",
        "RPP03A",
        "RPP04A",
        "RPP05A",
        "SLN01C",
        "SPVexp",
        "PUC09C",
    ]:
        print("This camera trap doesn't quite fit the schema. Skipping...")
        continue
    area, _ = Area.objects.get_or_create(name=rec["Unnamed: 1"].strip())
    county, _ = County.objects.get_or_create(name=rec["County"].strip(), area=area)
    grid, _ = Grid.objects.get_or_create(name=rec["Grid"].strip()) if rec["Grid"] else (None, None)
    macrosite_name = rec["Macro-Site"] if rec["Macro-Site"] else "N/A"
    macro_site, _ = MacroSite.objects.get_or_create(name=rec["Macro-Site"].strip(), county=county)
    microsite_name = rec["Micro-Site"] if rec["Micro-Site"] else "N/A"
    micro_site, _ = MicroSite.objects.get_or_create(name=rec["Micro-Site"].strip(), macro_site=macro_site, grid=grid)

    trail_type, _ = (
        TrailType.objects.get_or_create(name=rec["Trail-type (dropdown)"].strip())
        if rec["Trail-type (dropdown)"]
        else (None, None)
    )
    habitat_type, _ = (
        HabitatType.objects.get_or_create(name=rec["Habitat type"].strip()) if rec["Habitat type"] else (None, None)
    )
    secondary_habitat_type, _ = (
        HabitatType.objects.get_or_create(name=rec["Secondary Habitat Type"].strip())
        if rec["Secondary Habitat Type"]
        else (None, None)
    )
    camera_trap_obj, _ = CameraTrap.objects.get_or_create(
        trap_id=camera_trap_id,
        latitude=rec["Latitude"],
        longitude=rec["Longitude"],
        micro_site=micro_site,
        trail_type=trail_type,
        habitat_type=habitat_type,
        date_deployed=datetime.strptime(rec["Date Deployed"], "%m/%d/%Y").date(),
    )
    camera_trap_obj.secondary_habitat_type = secondary_habitat_type

    elevation = None
    elevation_unit = None
    if "ft" in rec["Elevation (ft)"]:
        elevation = int(rec["Elevation (ft)"].replace("ft", "").strip())
        elevation_unit = "ft"
    elif "m" in rec["Elevation (ft)"]:
        elevation = int(rec["Elevation (ft)"].replace("m", "").strip())
        elevation_unit = "m"

    camera_trap_obj.elevation = elevation
    camera_trap_obj.elevation_unit = elevation_unit

    if rec["Date Last Checked"].strip():
        try:
            camera_trap_obj.date_last_checked = datetime.strptime(rec["Date Last Checked"], "%m/%d/%Y").date()
        except:
            print(f"Format issue with 'Date Last Checked' field")
    if rec["Date to Be Checked"].strip():
        try:
            camera_trap_obj.date_to_be_checked = datetime.strptime(rec["Date to Be Checked"], "%m/%d/%Y").date()
        except:
            print(f"Format issue with 'Date to Be Checked' field")
            pass
    python_lock = None
    if rec["Python Lock #"].strip().isnumeric():
        if not PythonLock.objects.filter(number=rec["Python Lock #"]).exists():
            duplicate_key_exists = (
                True if rec["Duplicate Python Key?"] and rec["Duplicate Python Key?"] == "Y" else False
            )
            python_lock, _ = PythonLock.objects.get_or_create(
                number=rec["Python Lock #"].strip(),
                duplicate_key_exists=duplicate_key_exists,
            )

    camera_trap_obj.python_lock = python_lock
    padlock = rec["Padlock Type"] if rec["Padlock Type"] else ""
    if padlock:
        padlock, created = Padlock.objects.get_or_create(name=padlock)
        if not created:
            padlock.count += 1
            padlock.save()

    camera_trap_obj.instructions = rec["Contact before check?"]
    camera_trap_obj.picture_instructions = rec["Send pictures?"]
    camera_trap_obj.notes = rec["Comments"]

    camera_obj = None
    boxed = False
    camera_row = camera_inventory_df.loc[camera_inventory_df["Camera ID"] == camera_trap_id]
    if not camera_row.empty:
        camera_row = camera_row.to_dict(orient="records")[0]
        if Camera.objects.filter(serial_number=camera_row["Serial #"]).exists():
            camera_obj = Camera.objects.get(serial_number=camera_row["Serial #"])
        boxed = True if camera_row["Box?"] == "Yes" else False

    camera_trap_obj.camera = camera_obj
    camera_trap_obj.boxed = boxed

    camera_trap_obj.save()

    print(f"Successfully created record for camera trap with id- {camera_trap_id}")

# Create upload errors, error effects & action taken etc
errors = [
    "misfire",
    "batteries_died",
    "full_SD_card",
    "public_tampering",
    "environment",
    "user_error",
    "electronic_error",
    "no_night_flash",
    "fire_damage",
    "time_is_more_than_>4h_off",
    "unknown",
]

for error in errors:
    model, _ = UploadError.objects.get_or_create(error=error)

error_effects = [
    "missing_data",
    "misfire_data",
    "obstructed_view/camera_misplacement",
    "unknown",
    "none",
    "didnt_take_photos",
    "time corrected in EXIF date changer",
    "time not (yet) corrected",
    "day_time_only_pictures",
]

for error_effect in error_effects:
    model, _ = UploadErrorEffect.objects.get_or_create(error_effect=error_effect)

actions = [
    "checked",
    "taken_down",
    "moved",
    "replaced_camera",
]

for action in actions:
    model, _ = CameraTrapAction.objects.get_or_create(action=action)
