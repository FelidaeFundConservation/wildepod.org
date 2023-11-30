import torch
from ultralytics import YOLO

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

# Load a pretrained YOLO model (recommended for training)
model = YOLO("yolov8n.pt").to(device)

# Train the model using the 'coco128.yaml' dataset for 3 epochs
results = model.train(data="config.yaml", epochs=10)

# Evaluate the model's performance on the validation set
results = model.val()

# Perform object detection on an image using the model
# results = model("./datasets/wildepod/images/val/0c333207-9c1b-45c0-9ebc-bd1bd7cc1e7b.jpg")

# Export the model to ONNX format
success = model.export(format="onnx")
