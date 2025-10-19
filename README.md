# Vantage6 Node Manager

[![Docker Build](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-build.yml/badge.svg)](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-build.yml)
[![Docker Tests](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-test.yml/badge.svg)](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-test.yml)

This repository contains the code for a docker-based web-application to replace the Vantage6 CLI. The web-application is written in Python (Flask) and aims to make the setup process and management of (multiple) vantage6 nodes easier.

The current version of the Node Manager works specifically with Vantage6 version 4.x.x.

## Features

- 🌐 **Web-based Interface**: User-friendly dashboard for managing vantage6 nodes
- 🚀 **Easy Node Management**: Create, start, stop, restart, and delete node configurations
- 📊 **Real-time Monitoring**: View node status and container logs in real-time
- 🐳 **Docker Integration**: Seamless Docker container management for node instances
- 📝 **Configuration Management**: Simple form-based node configuration creation
- 📈 **Dashboard Overview**: Quick statistics and status of all nodes
- 🔄 **Multi-node Support**: Manage multiple node configurations from a single interface
- 🔍 **Automatic Version Detection**: Automatically detects server version and uses matching node image
- ⚙️ **Advanced Options**: Manual Docker image override for custom deployments

## Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ (if running without Docker)
- Access to a Vantage6 server (version 4.x.x)

## Quick Start

### Using Pre-built Docker Image (Easiest)

Pre-built images are automatically built and published via GitHub Actions.

1. **Pull the latest image**:
   ```bash
   docker pull ghcr.io/mdw-nl/vantage6-node-manager:latest
   ```

2. **Run with Docker**:
   ```bash
   docker run -d \
     --name vantage6-node-manager \
     -p 5000:5000 \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v ${HOME}/.config/vantage6:/root/.config/vantage6 \
     -e SECRET_KEY=$(openssl rand -hex 32) \
     ghcr.io/mdw-nl/vantage6-node-manager:latest
   ```

3. **Access the web interface**:
   Open your browser and navigate to `http://localhost:5000`

### Using Docker Compose (Recommended for Development)

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd vantage6-node-manager
   ```

2. **Create environment file**:
   ```bash
   cp .env.example .env
   # Edit .env and set your SECRET_KEY
   ```

3. **Start the application**:
   ```bash
   docker-compose up -d
   ```

4. **Access the web interface**:
   Open your browser and navigate to `http://localhost:5000`

### Manual Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd vantage6-node-manager
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```

5. **Access the web interface**:
   Open your browser and navigate to `http://localhost:5000`

## Usage

### Creating a Node Configuration

1. Navigate to **Nodes** > **Create New Node** in the web interface
2. Fill in the required information:
   - **Node Name**: A unique identifier for your node
   - **Server URL**: The URL of your Vantage6 server
   - **API Key**: Authentication key for the server
   - **Database Configuration**: Path to your data file and its type
3. Click **Create Node Configuration**

### Starting a Node

1. Go to the **Dashboard** or **All Nodes** page
2. Find your node in the list
3. Click the **Start** button (▶️)
4. The application will automatically detect the server version and use the appropriate node image
5. The node will start in a Docker container

**Note**: The node version is automatically determined by querying the server's `/api/version` endpoint. If you need to use a specific version, use the "Advanced Start" option in the node details page.

### Viewing Node Details

1. Click on a node name or the **View** button (👁️)
2. View detailed configuration information including auto-detected server version
3. See real-time container logs (for running nodes)
4. Access quick actions: Start, Stop, Restart, Delete

### Stopping a Node

1. Navigate to the node details page
2. Click the **Stop** button
3. The node container will be stopped gracefully

## Configuration

### Environment Variables

- `SECRET_KEY`: Flask secret key for session management (required in production)
- `FLASK_ENV`: Set to `production` or `development`
- `VANTAGE6_CONFIG_DIR`: Custom path for vantage6 configurations (optional)

### Node Configuration Files

Node configurations are stored as YAML files in:
- **User configurations**: `~/.config/vantage6/node/`
- **System configurations**: `/etc/vantage6/node/`

Example configuration structure:
```yaml
api_key: your-api-key
server_url: https://server.vantage6.ai
port: 443
api_path: /api
task_dir: /tmp/vantage6
databases:
  - label: default
    uri: /path/to/data.csv
    type: csv
logging:
  level: INFO
  file: my-node.log
encryption:
  enabled: false
```

## API Endpoints

The application provides REST API endpoints for programmatic access:

- `GET /api/nodes` - List all node configurations
- `GET /api/nodes/<name>/status` - Get status of a specific node
- `GET /api/server/version?server_url=<url>&api_path=<path>` - Check Vantage6 server version
- `GET /nodes/<name>/logs` - Get container logs for a running node

### Example: Check Server Version

```bash
curl "http://localhost:5000/api/server/version?server_url=https://server.vantage6.ai&api_path=/api"
```

Response:
```json
{
  "success": true,
  "version": "4.7.1",
  "server_url": "https://server.vantage6.ai",
  "recommended_image": "harbor2.vantage6.ai/infrastructure/node:4.7.1"
}
```

## Architecture

The application consists of:

1. **Flask Backend** (`app.py`):
   - Route handlers for web interface
   - Docker client integration
   - Configuration file management
   - Node lifecycle management

2. **HTML Templates** (`templates/`):
   - `base.html` - Base template with navigation
   - `index.html` - Dashboard with statistics
   - `nodes.html` - List of all nodes
   - `new_node.html` - Node creation form
   - `view_node.html` - Node details and logs

3. **Docker Integration**:
   - Uses Docker Python SDK to manage containers
   - Mounts configuration files and data into containers
   - Manages container lifecycle (create, start, stop, remove)

## Development

### Running in Development Mode

```bash
export FLASK_ENV=development
python app.py
```

The application will run with debug mode enabled and auto-reload on code changes.

### Building Docker Image

```bash
docker build -t vantage6-node-manager .
```

### Running Tests

```bash
# TODO: Add tests
pytest
```

## Troubleshooting

### Docker Connection Issues

**Problem**: "Docker is not running or not accessible"

**Solution**: 
- Ensure Docker daemon is running
- Check Docker socket permissions: `ls -la /var/run/docker.sock`
- If using Docker Compose, verify the socket is mounted correctly

### Node Won't Start

**Problem**: Node fails to start with error

**Solution**:
- Check the node configuration file for errors
- Verify the API key is correct
- Ensure database files exist and are accessible
- Check Docker logs: `docker logs <container-name>`

### Cannot Access Web Interface

**Problem**: Cannot connect to `http://localhost:5000`

**Solution**:
- Verify the application is running: `docker ps` or check the terminal
- Check if port 5000 is available: `lsof -i :5000`
- If using Docker, ensure port mapping is correct in docker-compose.yml

## Security Considerations

- **Change the default SECRET_KEY** in production
- Store sensitive information (API keys) securely
- Use HTTPS in production environments
- Restrict Docker socket access appropriately
- Consider implementing authentication for the web interface

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[Add your license here]

## Support

For issues and questions:
- Create an issue in the GitHub repository
- Contact the Vantage6 community

## Acknowledgments

- Built for [Vantage6](https://vantage6.ai/) - Privacy-preserving Federated Learning infrastructure
- Uses Bootstrap 5 for UI components
- Powered by Flask and Docker

## Roadmap

Future enhancements:
- [ ] User authentication and authorization
- [ ] Multi-user support with role-based access
- [ ] Advanced log filtering and search
- [ ] Node health monitoring and alerts
- [ ] Backup and restore configurations
- [ ] Algorithm store integration
- [ ] Task execution monitoring
- [ ] WebSocket support for real-time updates
- [ ] Export/import node configurations
- [ ] Batch operations on multiple nodes