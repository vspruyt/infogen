from fastapi import FastAPI

# Create the FastAPI app instance
app = FastAPI()

# Define a simple route
@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

