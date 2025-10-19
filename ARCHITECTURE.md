# Vantage6 Node Manager - Project Structure

```
vantage6-node-manager/
│
├── app.py                      # Main Flask application
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker image definition
├── docker-compose.yml          # Docker Compose configuration
├── setup.sh                    # Setup script (executable)
├── .env.example               # Environment variables template
├── .gitignore                 # Git ignore rules
├── README.md                  # Main documentation
├── GETTING_STARTED.md         # Quick start guide
│
└── templates/                 # HTML templates (Jinja2)
    ├── base.html             # Base template with navigation
    ├── index.html            # Dashboard page
    ├── nodes.html            # Node list page
    ├── new_node.html         # Create node form
    └── view_node.html        # Node details & logs page
```

## Key Components

### Application Layer (`app.py`)

**Routes:**
- `/` - Dashboard with statistics
- `/nodes` - List all node configurations
- `/nodes/new` - Create new node form
- `/nodes/<name>` - View node details
- `/nodes/<name>/start` - Start a node
- `/nodes/<name>/stop` - Stop a node
- `/nodes/<name>/restart` - Restart a node
- `/nodes/<name>/logs` - Get node logs (API)
- `/nodes/<name>/delete` - Delete node configuration

**API Endpoints:**
- `/api/nodes` - List nodes (JSON)
- `/api/nodes/<name>/status` - Get node status (JSON)

**Core Functions:**
- `get_docker_client()` - Initialize Docker client
- `get_node_configs()` - Read all node YAML configs
- `get_running_nodes()` - Query Docker for running containers
- `get_node_status()` - Check if a specific node is running

### Templates Layer (`templates/`)

**Base Template (`base.html`):**
- Navigation bar
- Sidebar menu
- Flash message system
- Responsive layout with Bootstrap 5

**Dashboard (`index.html`):**
- Statistics cards (total, running, stopped nodes)
- Quick actions
- Recent nodes list
- Running containers overview

**Node List (`nodes.html`):**
- Comprehensive table of all nodes
- Status indicators
- Quick action buttons
- Database information

**Create Node (`new_node.html`):**
- Form for node configuration
- Input validation
- Help cards with examples
- Toggle API key visibility

**Node Details (`view_node.html`):**
- Configuration details
- Container information
- Real-time logs with auto-refresh
- Control buttons (start/stop/restart/delete)

### Docker Layer

**Dockerfile:**
- Python 3.11 slim base image
- Flask application setup
- Health check configuration
- Port 5000 exposure

**docker-compose.yml:**
- Service definition
- Volume mounts (Docker socket, configs, data)
- Network configuration
- Environment variables
- Restart policy

## Data Flow

### Creating a Node

1. User fills form in browser (`new_node.html`)
2. POST request to `/nodes/new`
3. `app.py` validates input
4. Creates YAML config in `~/.config/vantage6/node/`
5. Redirects to node list with success message

### Starting a Node

1. User clicks start button
2. POST request to `/nodes/<name>/start`
3. `app.py` reads node configuration
4. Uses Docker SDK to create/start container
5. Mounts config file and data volumes
6. Returns to node details page

### Viewing Logs

1. Browser loads node details page
2. JavaScript fetches `/nodes/<name>/logs`
3. `app.py` queries Docker container logs
4. Returns JSON with log content
5. JavaScript updates page and sets auto-refresh

## Configuration Storage

**Node Configurations:**
```
~/.config/vantage6/node/
├── node1.yaml
├── node2.yaml
└── node3.yaml
```

**YAML Structure:**
```yaml
api_key: "secret"
server_url: "https://server.example.com"
port: 443
api_path: "/api"
task_dir: "/tmp/vantage6"
databases:
  - label: "default"
    uri: "/data/file.csv"
    type: "csv"
logging:
  level: "INFO"
  file: "node.log"
encryption:
  enabled: false
```

## Docker Container Management

**Container Naming:**
- Pattern: `vantage6-{node_name}-{user|system}`
- Example: `vantage6-hospital-a-user`

**Container Configuration:**
- Image: `harbor2.vantage6.ai/infrastructure/node:4.7.1`
- Volumes: Config file, database files
- Environment: `VANTAGE6_CONFIG_FILE`
- Labels: `vantage6-type=node`, `vantage6-name={name}`

## Technology Stack

**Backend:**
- Flask 3.0.0 - Web framework
- Docker SDK - Container management
- PyYAML - Configuration parsing

**Frontend:**
- Bootstrap 5.3.0 - UI framework
- Bootstrap Icons - Icon library
- Vanilla JavaScript - Interactivity

**Infrastructure:**
- Docker - Containerization
- Docker Compose - Orchestration
- Python 3.11 - Runtime

## Security Considerations

**Environment Variables:**
- SECRET_KEY stored in `.env` (not in git)
- Generated randomly during setup

**Docker Socket:**
- Mounted read/write for container management
- Requires appropriate host permissions

**API Keys:**
- Stored in YAML configs
- Password input field (toggleable visibility)
- Not exposed in API responses

**Future Enhancements:**
- Add user authentication
- Implement RBAC (Role-Based Access Control)
- Encrypt sensitive config data
- Add audit logging
