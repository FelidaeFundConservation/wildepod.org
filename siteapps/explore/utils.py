import base64
from io import BytesIO

from PIL import Image
import requests


# Function to get a PIL Image from an HTTP url
def load_web_image(image_url: str) -> Image:
    """Function to load an image from a web url"""
    # Retrieve the image content
    response = requests.get(image_url)

    # Directly try to load the returned data with pillow. If it fails, handle it downstream.
    image = Image.open(BytesIO(response.content))

    return image


# Function to get a PIL Image from a string
def load_image_from_binary_string(image_byte_string: str) -> Image:
    """Function to load an image directly from a binary string"""
    # Directly try to load the returned data with pillow. If it fails, handle it downstream.
    image_binary = base64.decodebytes(image_byte_string.encode())

    image = Image.open(BytesIO(image_binary))

    return image
