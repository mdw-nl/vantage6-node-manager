# Vantage6 Node Manager - Quick Reference

## Common Commands

### Starting the Application

```bash
# Using Docker Compose (recommended)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop application
docker-compose down
```

### Manual Python Execution

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run application
python app.py
```

## Web Interface Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Dashboard with statistics |
| `/nodes` | GET | List all nodes |
| `/nodes/new` | GET/POST | Create new node |
| `/nodes/<name>` | GET | View node details |
| `/nodes/<name>/start` | POST | Start node |
| `/nodes/<name>/stop` | POST | Stop node |
| `/nodes/<name>/restart` | POST | Restart node |
| `/nodes/<name>/delete` | POST | Delete node config |
| `/nodes/<name>/logs` | GET | Get logs (JSON) |

## API Endpoints

```bash
# List all nodes
curl http://localhost:5000/api/nodes

# Get node status
curl http://localhost:5000/api/nodes/my-node/status

# Get logs
curl http://localhost:5000/nodes/my-node/logs
```

## Configuration Locations

### User Configurations
```
~/.config/vantage6/node/
```

### System Configurations
```
/etc/vantage6/node/
```

### Environment File
```
.env
```

## Node Configuration Template

```yaml
api_key: "your-api-key-here"
server_url: "https://your-server.com"
port: 443
api_path: "/api"
task_dir: "/tmp/vantage6"
databases:
  - label: "default"
    uri: "/path/to/data.csv"
    type: "csv"
logging:
  level: "INFO"
  file: "node.log"
encryption:
  enabled: false
```

## Docker Commands

```bash
# View running containers
docker ps | grep vantage6

# View logs of a specific node
docker logs vantage6-my-node-user

# Stop a specific node
docker stop vantage6-my-node-user

# Remove a stopped container
docker rm vantage6-my-node-user

# View all vantage6 containers (including stopped)
docker ps -a | grep vantage6
```

## Troubleshooting Commands

```bash
# Check Docker daemon status
docker info

# Check if port 5000 is in use
lsof -i :5000  # Mac/Linux
netstat -an | findstr 5000  # Windows

# View application logs
docker-compose logs vantage6-node-manager

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Check Docker socket permissions
ls -la /var/run/docker.sock
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session secret | (random) |
| `FLASK_ENV` | Environment mode | production |
| `VANTAGE6_CONFIG_DIR` | Config directory | ~/.config/vantage6/node |

## File Permissions

```bash
# Make setup script executable
chmod +x setup.sh

# Fix Docker socket permissions (Linux)
sudo chmod 666 /var/run/docker.sock
# or add user to docker group
sudo usermod -aG docker $USER
```

## Common Issues & Solutions

### Issue: "Docker is not running"
```bash
# Start Docker daemon
sudo systemctl start docker  # Linux
# or restart Docker Desktop (Mac/Windows)
```

### Issue: "Permission denied" for Docker socket
```bash
# Add user to docker group
sudo usermod -aG docker $USER
# Then logout and login again
```

### Issue: Port 5000 already in use
```bash
# Find process using port
lsof -i :5000
# Kill the process or change port in docker-compose.yml
```

### Issue: Node configuration not found
```bash
# Check config directory
ls -la ~/.config/vantage6/node/
# Ensure .yaml extension is used
```

### Issue: Node won't start
```bash
# Check Docker logs
docker logs vantage6-<node-name>-user
# Verify configuration syntax
cat ~/.config/vantage6/node/<node-name>.yaml
```

## Development Tips

```bash
# Run in development mode
export FLASK_ENV=development
python app.py

# Auto-reload on changes (Flask debug mode)
export FLASK_DEBUG=1
python app.py

# Format code with black
pip install black
black app.py
```

## Useful Aliases

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
# Quick access to node configs
alias v6configs="cd ~/.config/vantage6/node"

# View all vantage6 containers
alias v6ps="docker ps | grep vantage6"

# View node manager logs
alias v6logs="docker-compose logs -f vantage6-node-manager"

# Restart node manager
alias v6restart="docker-compose restart vantage6-node-manager"
```

## Python Dependencies

```
Flask==3.0.0
PyYAML==6.0.1
docker==7.0.0
Werkzeug==3.0.1
```

## Default Node Image

```
harbor2.vantage6.ai/infrastructure/node:4.7.1
```

## URLs

- **Web Interface**: http://localhost:5000
- **API Documentation**: http://localhost:5000/api/nodes
- **Vantage6 Docs**: https://docs.vantage6.ai

## Status Indicators

| Badge | Status | Description |
|-------|--------|-------------|
| 🟢 Running | running | Node is active |
| 🔴 Stopped | stopped | Node is not running |
| 🟡 Unknown | unknown | Status cannot be determined |
