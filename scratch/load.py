# Run using python manage.py shell --settings=config.settings.local < scratch/load.py

import pandas as pd
from django.conf import settings
from images.models import Bot, CameraStationAction, SpeciesName
from inventory.models import Camera, CameraBrand, CameraModel, Padlock, PythonLock
from locations.models import Area, CameraStation, County, Grid, HabitatType, MacroSite, MicroSite, TrailType


def load_camera_inventory():
    # Download camera inventory data sheet as tsv into the local folder and rename as necessary
    camera_inventory_df = pd.read_csv("local/camera_inventory.tsv", delimiter="\t").fillna("")
    # Load camera inventory
    for i, rec in camera_inventory_df.iterrows():
        if not rec["Serial #"].strip():
            # print(f'---- SKIPPED - (Row - {i+2}) MISSING Serial number ---')
            continue

        if len(rec["Serial #"]) >= 24:
            # print(f'---- SKIPPED -  (Row - {i+2}) SERIAL NUMBER TOO LONG ---')
            continue

        # print(f'(Row - {i}) Loading Camera with Serial number - {rec["Serial #"]}')
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
            # print(f'---- SKIPPED -  (Row - {i+2}) MISSING STATUS ---')
            continue
        if not Camera.objects.filter(serial_number=rec["Serial #"]).exists():
            camera, _ = Camera.objects.get_or_create(
                serial_number=rec["Serial #"].strip(),
                model=model,
                status=status,
                comments=rec["Reason camera needs to be refurbished"],
            )
            # print(f'Successfully created record for camera with serial number - {rec["Serial #"]}')


load_camera_inventory()


def load_species_names():
    species_df = pd.read_csv("local/species.tsv", delimiter="\t").fillna("")
    for i, rec in species_df.iterrows():
        print(f'(Row - {i}) Loading Species Name - {rec["Scientific Name"]}')
        model, _ = SpeciesName.objects.get_or_create(name=rec["Common Name"], scientific_name=rec["Scientific Name"])


load_species_names()


def load_active_cameras():
    active_cameras_df = pd.read_csv("local/active_cameras.tsv", delimiter="\t").fillna("")
    active_cameras_df["deployment_date"] = pd.to_datetime(active_cameras_df["Camera.Deployment.Begin.Date"])
    # print(f"(Row - {i+2}) Loading Camera station with id - {camera_station_id}")
    # inactive_cameras_df = pd.read_csv("local/inactive_cameras.tsv", delimiter="\t").fillna("")
    # Load active camera stations
    for i, rec in active_cameras_df.iterrows():
        camera_station_id = rec["CameraStationID"].strip()
        latitude = float(rec["Latitude Y"])
        longitude = float(rec["Longitude X"])
        if not camera_station_id:
            print(f"(Row - {i+2}) Missing camera station id")
        if not latitude or not longitude:
            print(f"(Row - {i+2}) Missing lat or long")
        if not rec["Area"].strip():
            print(f"(Row - {i+2}) Missing Area")
        if not rec["County"].strip():
            print(f"(Row - {i+2}) Missing County")
        if not rec["Macro-Site"].strip():
            print(f"(Row - {i+2}) Missing Macro-Site")
        if not rec["Micro-Site"].strip():
            print(f"(Row - {i+2}) Missing Micro-Site")
        if not rec["Elevation (m)"]:
            print(f"(Row - {i+2}) Missing Elevation")
        if not rec["Habitat type"]:
            print(f"(Row - {i+2}) Missing Habitat type")
        if not rec["deployment_date"]:
            print(f"(Row - {i+2}) Missing Deployment date")
        date_deployed = rec["deployment_date"].date()

        elevation = int(rec["Elevation (m)"])
        elevation_unit = "m"

        habitat_type, _ = (
            HabitatType.objects.get_or_create(name=rec["Habitat type"].strip())
            if rec["Habitat type"].strip()
            else (None, None)
        )

        area, created = Area.objects.get_or_create(name=rec["Area"].strip())
        if created:
            print(f"Created area - {area.name}")
        county, created = County.objects.get_or_create(name=rec["County"].strip(), area=area)
        if created:
            print(f"Created county - {county.name}")
        macro_site, created = MacroSite.objects.get_or_create(name=rec["Macro-Site"].strip(), county=county)
        if created:
            print(f"Created macro site - {macro_site.name}")
        micro_site, created = MicroSite.objects.get_or_create(name=rec["Micro-Site"].strip(), macro_site=macro_site)
        if created:
            print(f"Created micro site - {micro_site.name}")

        # Create the core object
        camera_station_obj, created = CameraStation.objects.get_or_create(
            station_id=camera_station_id,
            latitude=latitude,
            longitude=longitude,
            micro_site=micro_site,
            date_deployed=date_deployed,
        )
        if created:
            print(f"Created camera station - {camera_station_id}")

        # Add elevation
        camera_station_obj.elevation = elevation
        camera_station_obj.elevation_unit = elevation_unit

        # Add habitat type
        if habitat_type:
            camera_station_obj.habitat_types.add(habitat_type)

        # Add comments
        camera_station_obj.comments = rec["Comments"].strip()

        # Add padlock
        padlock = rec["Padlock Type"].strip() if rec["Padlock Type"].strip() else None
        if padlock:
            padlock, created = Padlock.objects.get_or_create(name=padlock)
            if not created:
                padlock.count += 1
                padlock.save()
            camera_station_obj.padlock = padlock

        camera_station_obj.save()

    actions = [
        "checked",
        "taken_down",
        "moved",
        "replaced_camera",
    ]

    for action in actions:
        model, _ = CameraStationAction.objects.get_or_create(action=action)


load_active_cameras()
