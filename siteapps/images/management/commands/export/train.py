import torch
from ultralytics import YOLO

device = "cuda" if torch.cuda.is_available() else "cpu"

resume_pt = "./runs/detect/train/weights/last.pt"
pt = "yolov8n.pt"

# Load a pretrained YOLO model (recommended for training)
model = YOLO(pt).to(device)

if __name__ == "__main__":
    print(f"Using device: {device}")

    # Train the model using the 'coco128.yaml' dataset for x epochs
    results = model.train(data="config.yaml", epochs=300, batch=-1, workers=4, exist_ok=True, pretrained="best.pt")
    # results = model.train(resume=True)

    # Evaluate the model's performance on the validation set
    results = model.val()

    # Export the model to ONNX format
    success = model.export(format="onnx")
