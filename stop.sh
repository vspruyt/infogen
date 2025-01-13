# Stop existing container
docker ps -q --filter "name=infogen-container" | xargs -r docker stop
