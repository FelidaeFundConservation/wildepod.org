import torch
from ultralytics import YOLO

device = "cuda" if torch.cuda.is_available() else "cpu"

# Load a pretrained YOLO model (recommended for training)
model = YOLO("./runs/detect/train/weights/last.pt").to(device)

if __name__ == "__main__":
    print(f"Using device: {device}")

    # Train the model using the 'coco128.yaml' dataset for x epochs
    # results = model.train(data="config.yaml", epochs=600, batch=-1, workers=1, exist_ok=True, resume=True)
    results = model.train(resume=True)
    # Evaluate the model's performance on the validation set
    results = model.val()

    # Perform object detection on an image using the model
    # results = model("./datasets/wildepod/images/val/0c333207-9c1b-45c0-9ebc-bd1bd7cc1e7b.jpg")

    # Export the model to ONNX format
    success = model.export(format="onnx")
