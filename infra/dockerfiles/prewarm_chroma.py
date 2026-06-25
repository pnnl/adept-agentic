# infra/dockerfiles/azure/prewarm_chroma.py
import chromadb
import os

print("Starting ChromaDB pre-warming script...")

# The purpose of this script is to trigger the download of the default 
# sentence transformer model used by ChromaDB during the Docker build process.
# We create an ephemeral client, which stores data in memory.
client = chromadb.Client()

# Creating a collection is the action that triggers the model download if it's not cached.
# The collection itself is temporary and will not be part of the final image.
print("Creating temporary collection to trigger model download...")
try:
    collection = client.get_or_create_collection(name="prewarm-collection")
    print("Successfully created collection. Model should be cached now.")
    
    # Optional: Add a dummy document to be certain embedding is triggered.
    collection.add(
        documents=["This is a pre-warming document."],
        metadatas=[{"source": "prewarm"}],
        ids=["prewarm-doc-1"]
    )
    print("Dummy document added to trigger embedding.")

except Exception as e:
    print(f"An error occurred during pre-warming: {e}")
    # Exit with a non-zero code to fail the Docker build if something goes wrong.
    exit(1)

print("ChromaDB pre-warming script finished successfully.")
