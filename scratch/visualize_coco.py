#!/usr/bin/env python
"""
Visualize COCO Camera Traps format with bounding boxes and species labels.

Usage:
    uv run scratch/visualize_coco.py ../lila/lila_export_3_samplee_coco.json ../lila/sample_E --count 10

    # Show only images with 2+ bounding boxes
    uv run scratch/visualize_coco.py ../lila/coco.json ../lila/images --min-bboxes 2

    # Show only images with 2+ different species
    uv run scratch/visualize_coco.py ../lila/coco.json ../lila/images --min-species 2

    # Show only images from a specific camera station
    uv run scratch/visualize_coco.py ../lila/coco.json ../lila/images --location 31

Controls:
    - Press any key or close the window to advance to the next image
    - Press 'q' to quit early
"""
import argparse
import random
import sys
from pathlib import Path

import matplotlib.patches as patches
import matplotlib.pyplot as plt
from PIL import Image


def load_coco_data(json_path):
    """Load and parse COCO JSON file."""
    import json

    with open(json_path) as f:
        data = json.load(f)

    # Build category lookup
    categories = {cat["id"]: cat["name"] for cat in data["categories"]}

    # Build image lookup
    images = {img["id"]: img for img in data["images"]}

    # Group annotations by image
    annotations_by_image = {}
    for ann in data["annotations"]:
        image_id = ann["image_id"]
        if image_id not in annotations_by_image:
            annotations_by_image[image_id] = []
        annotations_by_image[image_id].append(ann)

    return images, categories, annotations_by_image


def visualize_image(image_path, image_info, annotations, categories):
    """Display image with bounding boxes and species labels."""
    # Load image
    img = Image.open(image_path)
    width, height = img.size

    # Create figure
    fig, ax = plt.subplots(1, figsize=(12, 8))
    ax.imshow(img)

    # Color palette for different species
    colors = plt.cm.tab10.colors

    # Draw bounding boxes
    for i, ann in enumerate(annotations):
        bbox = ann["bbox_relative"]
        x, y, w, h = bbox

        # Convert normalized coords to pixels
        x_px = x * width
        y_px = y * height
        w_px = w * width
        h_px = h * height

        # Get species name and color
        category_id = ann["category_id"]
        species = categories.get(category_id, f"Unknown ({category_id})")
        color = colors[category_id % len(colors)]

        # Draw rectangle
        rect = patches.Rectangle(
            (x_px, y_px),
            w_px,
            h_px,
            linewidth=2,
            edgecolor=color,
            facecolor="none",
        )
        ax.add_patch(rect)

        # Add label
        ax.text(
            x_px,
            y_px - 5,
            species,
            color="white",
            fontsize=10,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=color, alpha=0.8),
        )

    # Set title with image info
    title = f"File: {image_info['file_name']}"
    if "datetime" in image_info:
        title += f"\nDatetime: {image_info['datetime']}"
    if "location" in image_info:
        title += f" | Location: {image_info['location']}"
    ax.set_title(title, fontsize=10)

    ax.axis("off")
    plt.tight_layout()

    # Show and wait for keypress
    plt.show(block=True)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Visualize COCO Camera Traps data")
    parser.add_argument("json_file", help="Path to COCO JSON file")
    parser.add_argument("image_dir", help="Path to image directory")
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of random images to display (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--min-bboxes",
        type=int,
        default=1,
        help="Minimum number of bounding boxes per image (default: 1)",
    )
    parser.add_argument(
        "--min-species",
        type=int,
        default=1,
        help="Minimum number of unique species per image (default: 1)",
    )
    parser.add_argument(
        "--location",
        type=str,
        default=None,
        help="Filter by camera station ID / location (e.g., 31)",
    )
    args = parser.parse_args()

    json_path = Path(args.json_file)
    image_dir = Path(args.image_dir)

    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)

    if not image_dir.exists():
        print(f"Error: Image directory not found: {image_dir}")
        sys.exit(1)

    # Load data
    print(f"Loading COCO data from {json_path}...")
    images, categories, annotations_by_image = load_coco_data(json_path)
    print(f"  Found {len(images)} images, {len(categories)} categories")

    # Filter images by min bboxes, min species, and location
    image_ids = list(images.keys())
    has_filters = args.min_bboxes > 1 or args.min_species > 1 or args.location is not None

    if has_filters:
        filtered_ids = []
        for img_id in image_ids:
            img_info = images[img_id]
            anns = annotations_by_image.get(img_id, [])
            num_bboxes = len(anns)
            num_species = len(set(ann["category_id"] for ann in anns))

            # Check location filter
            if args.location is not None:
                if img_info.get("location") != args.location:
                    continue

            if num_bboxes >= args.min_bboxes and num_species >= args.min_species:
                filtered_ids.append(img_id)

        filter_desc = []
        if args.min_bboxes > 1:
            filter_desc.append(f"min_bboxes={args.min_bboxes}")
        if args.min_species > 1:
            filter_desc.append(f"min_species={args.min_species}")
        if args.location:
            filter_desc.append(f"location={args.location}")
        print(f"  After filtering ({', '.join(filter_desc)}): {len(filtered_ids)} images")
        image_ids = filtered_ids

    if not image_ids:
        print("No images match the filter criteria.")
        sys.exit(0)

    # Select random subset
    if args.seed is not None:
        random.seed(args.seed)
    count = min(args.count, len(image_ids))
    selected_ids = random.sample(image_ids, count)

    print(f"\nDisplaying {count} random images...")
    print("Close each window or press any key to advance. Press 'q' to quit.\n")

    # Display images
    for i, image_id in enumerate(selected_ids, 1):
        image_info = images[image_id]
        file_name = image_info["file_name"]
        image_path = image_dir / file_name

        if not image_path.exists():
            print(f"[{i}/{count}] MISSING: {file_name}")
            continue

        annotations = annotations_by_image.get(image_id, [])
        species_list = [categories.get(a["category_id"], "?") for a in annotations]

        print(f"[{i}/{count}] {file_name} - {len(annotations)} bbox(es): {', '.join(species_list)}")

        try:
            visualize_image(image_path, image_info, annotations, categories)
        except KeyboardInterrupt:
            print("\nQuitting...")
            break

    print("\nDone!")


if __name__ == "__main__":
    main()
