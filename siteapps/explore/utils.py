# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import base64
from io import BytesIO

import requests
from PIL import Image


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
