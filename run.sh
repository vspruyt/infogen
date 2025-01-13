#!/bin/bash

# Stop and remove any existing container
docker ps -q --filter "name=infogen-container" | xargs -r docker stop
docker ps -aq --filter "name=infogen-container" | xargs -r docker rm

# Run the container with a volume mount
docker run -d -p 8000:80 --name infogen-container -v $(pwd):/infogen infogen

# Print the status
echo "App is running at http://localhost:8000 with auto-reload enabled"

