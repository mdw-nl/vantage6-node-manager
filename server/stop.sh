#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE_MANAGER_CONTAINER="vantage6-node-manager"
SERVER_NETWORK="vantage6-server-network"

echo "[server] Disconnecting node manager from server network..."
docker network disconnect "$SERVER_NETWORK" "$NODE_MANAGER_CONTAINER" 2>/dev/null || true

echo "[server] Stopping server..."
docker compose -f "$SCRIPT_DIR/docker-compose.server.yml" down

echo "[server] Done"
