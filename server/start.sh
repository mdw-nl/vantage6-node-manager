#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_CONTAINER="vantage6-demoserver-user"
SERVER_NETWORK="vantage6-server-network"
NODE_MANAGER_CONTAINER="vantage6-node-manager"
echo "[server] Starting vantage6 server..."
docker compose -f "$SCRIPT_DIR/docker-compose.server.yml" up -d

echo "[server] Waiting for server to be ready at http://localhost:5070/api/health..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:5070/api/health > /dev/null 2>&1; then
        echo "[server] Server is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[server] ERROR: Server did not become ready in time"
        docker logs "$SERVER_CONTAINER"
        exit 1
    fi
    sleep 2
done

# Check if organizations already exist in the database by querying the API
ORG_COUNT=$(curl -s http://localhost:5070/api/organization | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_count', len(d.get('data', []))))" 2>/dev/null || echo "0")
if [ "$ORG_COUNT" -eq 0 ] 2>/dev/null; then
    echo "[server] Importing entities (organizations, collaboration, API keys)..."
    docker cp "$SCRIPT_DIR/entities.yaml" "$SERVER_CONTAINER:/entities.yaml"
    docker exec "$SERVER_CONTAINER" vserver-local import --config /mnt/config.yaml /entities.yaml
    echo "[server] Entities imported successfully"
else
    echo "[server] Database already has $ORG_COUNT organization(s), skipping import"
fi

if docker inspect "$NODE_MANAGER_CONTAINER" > /dev/null 2>&1; then
    if docker network inspect "$SERVER_NETWORK" --format '{{range .Containers}}{{.Name}} {{end}}' | grep -q "$NODE_MANAGER_CONTAINER"; then
        echo "[server] Node manager already connected to server network"
    else
        echo "[server] Connecting node manager to server network..."
        docker network connect "$SERVER_NETWORK" "$NODE_MANAGER_CONTAINER"
        echo "[server] Node manager connected"
    fi
else
    echo "[server] Node manager container not running, skipping network connect"
fi

echo "[server] Done. Server available at http://localhost:5070"
