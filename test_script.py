#!/usr/bin/env python
"""
Simple test script to verify the process_macrosite_images functionality.
Run this in Django shell to test the script.
"""

# Import the main function
exec(open('process_macrosite_images.py').read())

# Test the script with a small date range
print("Testing the script...")
print("=" * 50)

# First, let's see what macrosites are available
macrosites = MacroSite.objects.all()
if macrosites.exists():
    test_macrosite = macrosites.first()
    print(f"Using test macrosite: {test_macrosite.name}")
    
    # Get a date range that might have images
    sample_images = Image.objects.filter(
        upload__camera_station__micro_site__macro_site=test_macrosite,
        trigger_timestamp__isnull=False
    ).order_by('trigger_timestamp')[:5]
    
    if sample_images.exists():
        first_image = sample_images.first()
        last_image = sample_images.last()
        
        start_date = first_image.trigger_timestamp.strftime('%Y-%m-%d')
        end_date = last_image.trigger_timestamp.strftime('%Y-%m-%d')
        
        print(f"Testing with date range: {start_date} to {end_date}")
        
        # Test without downloading images first
        result = process_macrosite_images(
            macrosite_name=test_macrosite.name,
            start_date=start_date,
            end_date=end_date,
            download_images=False  # Set to False for initial testing
        )
        
        print("\nTest completed. Results:")
        print(f"Total images found: {result.get('total_images', 0)}")
        print(f"Processed images: {result.get('processed_images', 0)}")
        print(f"Errors: {len(result.get('errors', []))}")
        
        if result.get('results'):
            print(f"Sample image data keys: {list(result['results'][0].keys())}")
            print(f"Sample annotations count: {len(result['results'][0]['annotations'])}")
    else:
        print("No images found for this macrosite")
else:
    print("No macrosites found in database")