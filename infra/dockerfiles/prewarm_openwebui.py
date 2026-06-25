# infra/dockerfiles/prewarm_openwebui.py
import os
from sentence_transformers import SentenceTransformer

print("Starting OpenWebUI model pre-warming script...")

# Define the model to download and the cache directory inside the container
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CACHE_DIR = "/app/models"

print(f"Ensuring cache directory exists: {CACHE_DIR}")
os.makedirs(CACHE_DIR, exist_ok=True)

try:
    print(f"Downloading and caching sentence transformer model: {MODEL_NAME}")
    # By specifying the cache_folder, we control where the model is stored.
    # The library will download the model to this folder.
    model = SentenceTransformer(MODEL_NAME, cache_folder=CACHE_DIR)
    print("Model downloaded and cached successfully.")

    # Verify by trying to load it again from the cache (optional but good practice)
    print("Verifying model from cache...")
    model_from_cache = SentenceTransformer(MODEL_NAME, cache_folder=CACHE_DIR)
    print("Verification successful.")

except Exception as e:
    print(f"An error occurred during OpenWebUI model pre-warming: {e}")
    exit(1)

print("OpenWebUI model pre-warming script finished successfully.")
