#!/bin/bash

# Vantage6 Node Manager - Setup Script

echo "========================================="
echo "Vantage6 Node Manager - Setup"
echo "========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker is installed"
echo "✅ Docker Compose is installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    
    # Generate a random secret key
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    
    # Replace the secret key in .env file
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/your-secret-key-here-change-in-production/$SECRET_KEY/" .env
    else
        # Linux
        sed -i "s/your-secret-key-here-change-in-production/$SECRET_KEY/" .env
    fi
    
    echo "✅ .env file created with random SECRET_KEY"
else
    echo "✅ .env file already exists"
fi

echo ""

# Create vantage6 config directory if it doesn't exist
VANTAGE6_DIR="$HOME/.config/vantage6/node"
if [ ! -d "$VANTAGE6_DIR" ]; then
    echo "📁 Creating Vantage6 configuration directory..."
    mkdir -p "$VANTAGE6_DIR"
    echo "✅ Created: $VANTAGE6_DIR"
else
    echo "✅ Vantage6 config directory exists: $VANTAGE6_DIR"
fi

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Review and update .env file if needed"
echo "2. Start the application:"
echo "   docker-compose up -d"
echo ""
echo "3. Access the web interface:"
echo "   http://localhost:5000"
echo ""
echo "4. Stop the application:"
echo "   docker-compose down"
echo ""
