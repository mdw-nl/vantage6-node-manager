#!/bin/bash
set -e  # Exit on error

# Vantage6 Node Manager - Quick Start Script
# Usage: curl -fsSL https://raw.githubusercontent.com/mdw-nl/vantage6-node-manager/main/start.sh | bash

# Configuration
REPO_RAW_URL="https://raw.githubusercontent.com/mdw-nl/vantage6-node-manager/main"
INSTALL_DIR="${INSTALL_DIR:-$HOME/vantage6-node-manager}"

echo "========================================="
echo "Vantage6 Node Manager - Quick Start"
echo "========================================="
echo ""
echo "Installation directory: $INSTALL_DIR"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "✅ Docker is installed"

# Check if Docker Compose is available (either as plugin or standalone)
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
    echo "✅ Docker Compose (plugin) is installed"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
    echo "✅ Docker Compose (standalone) is installed"
else
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    echo "❌ Docker daemon is not running. Please start Docker first."
    exit 1
fi
echo "✅ Docker daemon is running"

echo ""

# Create installation directory
if [ ! -d "$INSTALL_DIR" ]; then
    echo "📁 Creating installation directory..."
    mkdir -p "$INSTALL_DIR"
    echo "✅ Created: $INSTALL_DIR"
else
    echo "✅ Installation directory exists: $INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Download necessary files
echo ""
echo "📥 Downloading production docker-compose file..."

# Download production docker-compose.yml (uses pre-built image)
echo "   - docker-compose.prod.yml"
curl -fsSL "$REPO_RAW_URL/docker-compose.prod.yml" -o docker-compose.yml

echo "✅ Files downloaded"

echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    
    # Generate a random secret key
    if command -v python3 &> /dev/null; then
        SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "vantage6-node-manager-secret-$(date +%s)")
    elif command -v openssl &> /dev/null; then
        SECRET_KEY=$(openssl rand -hex 32)
    else
        SECRET_KEY="vantage6-node-manager-secret-$(date +%s)"
        echo "⚠️  Using basic SECRET_KEY. Consider generating a secure key."
    fi
    
    cat > .env << EOF
# Vantage6 Node Manager Environment Configuration
SECRET_KEY=$SECRET_KEY
EOF
    
    echo "✅ .env file created with random SECRET_KEY"
else
    echo "✅ .env file already exists"
fi

echo ""

# Create vantage6 config directories if they don't exist
VANTAGE6_DIR="$HOME/.config/vantage6/node"
if [ ! -d "$VANTAGE6_DIR" ]; then
    echo "📁 Creating Vantage6 configuration directory..."
    mkdir -p "$VANTAGE6_DIR"
    echo "✅ Created: $VANTAGE6_DIR"
else
    echo "✅ Vantage6 config directory exists: $VANTAGE6_DIR"
fi

# Create system config directory
VANTAGE6_SYSTEM_DIR="$HOME/.config/vantage6-system"
if [ ! -d "$VANTAGE6_SYSTEM_DIR" ]; then
    echo "📁 Creating Vantage6 system configuration directory..."
    mkdir -p "$VANTAGE6_SYSTEM_DIR"
    echo "✅ Created: $VANTAGE6_SYSTEM_DIR"
else
    echo "✅ Vantage6 system config directory exists: $VANTAGE6_SYSTEM_DIR"
fi

# Create data directory
VANTAGE6_DATA_DIR="$HOME/.local/share/vantage6/node"
if [ ! -d "$VANTAGE6_DATA_DIR" ]; then
    echo "📁 Creating Vantage6 data directory..."
    mkdir -p "$VANTAGE6_DATA_DIR"
    echo "✅ Created: $VANTAGE6_DATA_DIR"
else
    echo "✅ Vantage6 data directory exists: $VANTAGE6_DATA_DIR"
fi

echo ""
echo "========================================="
echo "Starting Vantage6 Node Manager..."
echo "========================================="
echo ""

# Pull and start the application (using pre-built image)
echo "� Pulling latest Docker image..."
$DOCKER_COMPOSE pull

echo ""
echo "🚀 Starting application..."
$DOCKER_COMPOSE up -d

echo ""
echo "⏳ Waiting for application to be ready..."
sleep 5

# Check if container is running
if docker ps | grep -q vantage6-node-manager; then
    echo ""
    echo "========================================="
    echo "✅ Application Started Successfully!"
    echo "========================================="
    echo ""
    echo "📊 Access the web interface:"
    echo "   http://localhost:5000"
    echo ""
    echo "📝 View logs:"
    echo "   cd $INSTALL_DIR && $DOCKER_COMPOSE logs -f"
    echo ""
    echo "🛑 Stop the application:"
    echo "   cd $INSTALL_DIR && $DOCKER_COMPOSE down"
    echo ""
    echo "🔄 Restart the application:"
    echo "   cd $INSTALL_DIR && $DOCKER_COMPOSE restart"
    echo ""
    echo "📚 Documentation:"
    echo "   https://github.com/mdw-nl/vantage6-node-manager"
    echo ""
    echo "========================================="
else
    echo ""
    echo "⚠️  Container may not have started correctly."
    echo "   Check logs with: cd $INSTALL_DIR && $DOCKER_COMPOSE logs"
    echo ""
fi
