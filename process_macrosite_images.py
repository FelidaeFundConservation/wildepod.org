#!/usr/bin/env python
"""
Django shell script to process images from a specific macrosite within a date range.

Usage:
    python manage.py shell < process_macrosite_images.py

Or run interactively in Django shell:
    exec(open('process_macrosite_images.py').read())
"""

import os
import sys
import requests
import pickle
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

# Django imports
from django.db import transaction
from django.utils.dateparse import parse_datetime
from google.cloud import storage

# Model imports
from images.models.image import Image
from images.models.annotation import BoundingBox, Category, Species, Activity
from locations.models import MacroSite


def download_image_from_gcloud(gcloud_path, local_path):
    """
    Download image from Google Cloud Storage bucket to local path using public URL.
    
    Args:
        gcloud_path (str): Google Cloud Storage path (e.g., 'thumbnails/image.jpg')
        local_path (str): Local file path to save the image
        
    Returns:
        bool: True if download successful, False otherwise
    """
    try:
        # Get bucket name from Django settings
        from django.conf import settings
        bucket_name = settings.GS_BUCKET_NAME
        
        # Construct public URL for the file
        # Remove 'media/' prefix if it exists since MEDIA_URL already includes it
        clean_path = gcloud_path.replace('media/', '') if gcloud_path.startswith('media/') else gcloud_path
        public_url = f"https://storage.googleapis.com/{bucket_name}/media/{clean_path}"
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Download the file using HTTP request
        response = requests.get(public_url)
        response.raise_for_status()
        
        with open(local_path, 'wb') as f:
            f.write(response.content)
        
        print(f"Downloaded: {public_url} -> {local_path}")
        return True
        
    except Exception as e:
        print(f"Error downloading {gcloud_path}: {str(e)}")
        return False


def get_image_annotations(image):
    """
    Fetch all bounding box details and associated annotations for an image.
    
    Args:
        image (Image): The image instance
        
    Returns:
        list: List of dictionaries containing bounding box and annotation data
    """
    annotations = []
    
    # Get all bounding boxes for this image
    bounding_boxes = BoundingBox.objects.filter(image=image).prefetch_related(
        'accepted_by',
        'rejected_by'
    )
    
    for bbox in bounding_boxes:
        bbox_data = {
            'bbox_id': str(bbox.id),
            'coordinates': {
                'x': bbox.x,
                'y': bbox.y,
                'w': bbox.w,
                'h': bbox.h
            },
            'confidence': bbox.confidence,
            'confidence_threshold': bbox.confidence_threshold,
            'validity': bbox.validity,
            'created_by': str(bbox.created_by),
            'accepted_by': [str(annotator) for annotator in bbox.accepted_by.all()],
            'rejected_by': [str(annotator) for annotator in bbox.rejected_by.all()],
            'categories': [],
            'species': [],
            'activities': []
        }
        
        # Get category annotations
        categories = Category.objects.filter(bounding_box=bbox).prefetch_related('accepted_by', 'rejected_by')
        for category in categories:
            bbox_data['categories'].append({
                'id': str(category.id),
                'name': category.name,
                'confidence': category.confidence,
                'created_by': str(category.created_by),
                'accepted_by': [str(annotator) for annotator in category.accepted_by.all()],
                'rejected_by': [str(annotator) for annotator in category.rejected_by.all()]
            })
        
        # Get species annotations
        species_list = Species.objects.filter(bounding_box=bbox).select_related('name').prefetch_related('accepted_by', 'rejected_by')
        for species in species_list:
            bbox_data['species'].append({
                'id': str(species.id),
                'name': species.name.name,
                'scientific_name': species.name.scientific_name,
                'species_group': species.name.species_group,
                'confidence': species.confidence,
                'created_by': str(species.created_by),
                'accepted_by': [str(annotator) for annotator in species.accepted_by.all()],
                'rejected_by': [str(annotator) for annotator in species.rejected_by.all()]
            })
        
        # Get activity annotations
        activities = Activity.objects.filter(bounding_box=bbox).select_related('name').prefetch_related('accepted_by', 'rejected_by')
        for activity in activities:
            bbox_data['activities'].append({
                'id': str(activity.id),
                'name': activity.name.name,
                'category': activity.name.category,
                'confidence': activity.confidence,
                'created_by': str(activity.created_by),
                'accepted_by': [str(annotator) for annotator in activity.accepted_by.all()],
                'rejected_by': [str(annotator) for annotator in activity.rejected_by.all()]
            })
        
        annotations.append(bbox_data)
    
    return annotations


def process_macrosite_images(macrosite_name, start_date, end_date, download_images=True, force_refresh=False):
    """
    Main function to process images from a macrosite within a date range.
    
    Args:
        macrosite_name (str): Name of the macrosite
        start_date (str): Start date in ISO format (YYYY-MM-DD) or datetime string
        end_date (str): End date in ISO format (YYYY-MM-DD) or datetime string
        download_images (bool): Whether to download images from Google Storage
        force_refresh (bool): Whether to force refresh even if pickle file exists
        
    Returns:
        dict: Processing results and statistics
    """
    try:
        # Create output directory
        output_dir = Path("../test_images")
        output_dir.mkdir(exist_ok=True)
        
        # Create pickle filename based on parameters
        pickle_filename = f"{macrosite_name}_{start_date}_{end_date}.pkl"
        pickle_path = output_dir / pickle_filename
        
        # Check if pickle file already exists and force_refresh is False
        if pickle_path.exists() and not force_refresh:
            print(f"Pickle file already exists: {pickle_path}")
            print("Loading existing results...")
            
            try:
                with open(pickle_path, 'rb') as f:
                    existing_results = pickle.load(f)
                
                print(f"Loaded existing results:")
                print(f"Total images: {existing_results.get('total_images', 0)}")
                print(f"Downloaded images: {existing_results.get('downloaded_images', 0)}")
                print(f"Processed images: {existing_results.get('processed_images', 0)}")
                print("Use force_refresh=True to regenerate the data.")
                
                return existing_results
                
            except Exception as e:
                print(f"Error loading pickle file: {str(e)}")
                print("Proceeding with fresh processing...")
        
        elif force_refresh and pickle_path.exists():
            print(f"Force refresh requested. Regenerating data...")
        # Validate macrosite exists
        try:
            macrosite = MacroSite.objects.get(name=macrosite_name)
        except MacroSite.DoesNotExist:
            available_sites = MacroSite.objects.values_list('name', flat=True)
            print(f"Macrosite '{macrosite_name}' not found.")
            print(f"Available macrosites: {list(available_sites)}")
            return {"error": f"Macrosite '{macrosite_name}' not found"}
        
        # Parse dates
        try:
            if isinstance(start_date, str):
                start_date = parse_datetime(start_date + "T00:00:00Z") if 'T' not in start_date else parse_datetime(start_date)
            if isinstance(end_date, str):
                end_date = parse_datetime(end_date + "T23:59:59Z") if 'T' not in end_date else parse_datetime(end_date)
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid date format: {str(e)}"}
        
        print(f"Processing images for macrosite: {macrosite_name}")
        print(f"Date range: {start_date} to {end_date}")
        
        # Query images
        images = Image.objects.filter(
            upload__camera_station__micro_site__macro_site=macrosite,
            trigger_timestamp__gte=start_date,
            trigger_timestamp__lte=end_date
        ).select_related(
            'upload__camera_station__micro_site',
            'upload__camera_station'
        ).order_by('trigger_timestamp')
        
        total_images = images.count()
        print(f"Found {total_images} images in the specified date range")
        
        if total_images == 0:
            empty_result = {
                "macrosite": macrosite_name,
                "date_range": f"{start_date} to {end_date}",
                "total_images": 0,
                "downloaded_images": 0,
                "processed_images": 0,
                "errors": [],
                "results": []
            }
            # Save empty result to pickle
            with open(pickle_path, 'wb') as f:
                pickle.dump(empty_result, f)
            print(f"Saved empty results to: {pickle_path}")
            return empty_result
        
        # Process each image
        downloaded_count = 0
        processed_count = 0
        errors = []
        results = []
        
        for i, image in enumerate(images, 1):
            print(f"Processing image {i}/{total_images}: {image.dropbox_file_name}")
            
            try:
                # Prepare image data
                image_data = {
                    'image_id': str(image.id),
                    'filename': image.dropbox_file_name,
                    'file_path': image.dropbox_file_path,
                    'trigger_timestamp': image.trigger_timestamp.isoformat() if image.trigger_timestamp else None,
                    'camera_station': image.upload.camera_station.station_id,
                    'micro_site': image.upload.camera_station.micro_site.name,
                    'macro_site': macrosite_name,
                    'width': image.width,
                    'height': image.height,
                    'latitude': image.latitude,
                    'longitude': image.longitude,
                    'file_size': image.file_size,
                    'is_video': image.is_video,
                    'processed': image.processed,
                    'species_ai_detections': image.species_ai_detections,
                    'local_path': None,
                    'annotations': []
                }
                
                # Download image if requested and thumbnail path exists
                if download_images and image.thumbnail_gcloud_path:
                    # Create safe filename
                    safe_filename = f"{image.id}_{image.dropbox_file_name.replace('/', '_')}"
                    local_path = output_dir / safe_filename
                    
                    # Check if file already exists
                    if not local_path.exists():
                        if download_image_from_gcloud(image.thumbnail_gcloud_path, str(local_path)):
                            downloaded_count += 1
                            image_data['local_path'] = str(local_path)
                        else:
                            errors.append(f"Failed to download {image.dropbox_file_name}")
                    else:
                        print(f"File already exists: {local_path}")
                        image_data['local_path'] = str(local_path)
                        downloaded_count += 1
                
                # Get annotations
                image_data['annotations'] = get_image_annotations(image)
                
                print(image_data)
                results.append(image_data)
                processed_count += 1
                
            except Exception as e:
                error_msg = f"Error processing image {image.dropbox_file_name}: {str(e)}"
                errors.append(error_msg)
                print(error_msg)
        
        # Summary
        summary = {
            "macrosite": macrosite_name,
            "date_range": f"{start_date} to {end_date}",
            "total_images": total_images,
            "downloaded_images": downloaded_count,
            "processed_images": processed_count,
            "errors": errors,
            "results": results
        }
        
        print(f"\nProcessing completed!")
        print(f"Total images: {total_images}")
        print(f"Downloaded images: {downloaded_count}")
        print(f"Processed images: {processed_count}")
        print(f"Errors: {len(errors)}")
        
        # Save results to pickle file
        try:
            with open(pickle_path, 'wb') as f:
                pickle.dump(summary, f)
            print(f"Results saved to pickle file: {pickle_path}")
        except Exception as e:
            print(f"Warning: Could not save pickle file: {str(e)}")
        
        return summary
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(error_msg)
        return {"error": error_msg}


#Example usage:
result = process_macrosite_images(
    macrosite_name="SFPUC",
    start_date="2024-05-01",
    end_date="2024-06-01",
    download_images=True
)

## Print available macrosites for reference
#print("Available macrosites:")
#for macrosite in MacroSite.objects.all():
#    print(f"  - {macrosite.name}")
#
#print("\nTo use this script, call:")
#print("result = process_macrosite_images('MACROSITE_NAME', 'START_DATE', 'END_DATE')")
#print("Example: result = process_macrosite_images('Laikipia', '2024-01-01', '2024-01-31')")