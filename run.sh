#!/bin/bash

# Stop and remove any existing container
docker ps -q --filter "name=infogen-container" | xargs -r docker stop
docker ps -aq --filter "name=infogen-container" | xargs -r docker rm

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Warning: .env file not found"
    exit 1
fi

# Run the container with a volume mount and environment variables
docker run -d \
    -p 8000:80 \
    --name infogen-container \
    -v $(pwd):/infogen \
    --env-file .env \
    infogen

# Print the status
echo "App is running at http://localhost:8000 with auto-reload enabled"

