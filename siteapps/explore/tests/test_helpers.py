"""Helper functions for explore tests"""


def create_test_image(upload, file_path="test.jpg", **kwargs):
    """
    Create a test Image with all required fields populated.
    
    Args:
        upload: Upload instance
        file_path: Path to use for dropbox_file_path (default: "test.jpg")
        **kwargs: Additional fields to override
    
    Returns:
        Image instance
    """
    from images.models import Image
    
    defaults = {
        'dropbox_file_path': file_path,
        'dropbox_file_name': file_path.split('/')[-1],
        'dropbox_file_path_display': file_path,
        'dropbox_content_hash': 'abc123def456',
        'dropbox_file_id': f'id:{file_path}',
        'file_size': 1024,
    }
    defaults.update(kwargs)
    
    return Image.objects.create(upload=upload, **defaults)
