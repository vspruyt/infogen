from fastapi import FastAPI

# Create the FastAPI app instance
infogen = FastAPI()

# Define a simple route
@infogen.get("/")
def read_root():
    return {"message": "Hello, World reloaded!"}

