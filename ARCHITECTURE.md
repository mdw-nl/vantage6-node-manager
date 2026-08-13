# Vantage6 Node Manager - Project Structure

```
vantage6-node-manager/
│
├── app.py                      # Entrypoint: creates the Flask app, registers blueprints
├── nodemanager/                # Application package
│   ├── config.py               #   Path constants (VANTAGE6_CONFIG_DIR, USERS_FILE, ...)
│   ├── auth.py                 #   Blueprint: login/logout, user store, auth gate
│   ├── nodes.py                #   Blueprint: dashboard, node CRUD, view/logs/import/export
│   ├── node_actions.py         #   Blueprint: start/stop/restart, bulk actions
│   ├── api.py                  #   Blueprint: JSON /api/* endpoints
│   ├── docker_utils.py         #   Docker client, container/image lookups, volume/env building
│   ├── node_config.py          #   Reading node config YAML files
│   ├── server_api.py           #   Talking to the vantage6 server (version, health, tasks)
│   └── crypto.py               #   RSA key-pair generation
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker image definition
├── docker-compose.yml          # Docker Compose configuration (dev, builds from source)
├── docker-compose.prod.yml     # Docker Compose configuration (production, pre-built image)
├── start.sh                    # One-command install & start script (curl | bash)
├── .env.example               # Environment variables template
├── .gitignore                 # Git ignore rules
├── README.md                  # Main documentation
│
├── templates/                  # HTML templates (Jinja2)
│   ├── base.html               #   Base template with sidebar navigation
│   ├── login.html              #   Login form
│   ├── index.html              #   Dashboard page
│   ├── nodes.html               #   Node list page
│   ├── new_node.html           #   Create node form
│   ├── edit_node.html          #   Edit node form
│   ├── view_node.html          #   Node details, logs & task history
│   ├── import_node.html        #   Import node config/backup
│   ├── users.html              #   User list (admin only)
│   ├── new_user.html           #   Create user form (admin only)
│   └── audit.html              #   Activity log (admin only)
│
└── static/                     # CSS, images (mdw-theme.css, logo)
```

## Key Components

### Application Layer (`app.py` + `nodemanager/`)

`app.py` is a thin entrypoint (~35 lines): it creates the Flask app, calls
`auth.init_app(app)` (wires up Flask-Login and the app-wide auth gate), and
registers four blueprints. All actual route handlers and logic live in the
`nodemanager/` package, split by concern:

**`nodemanager/auth.py` — Blueprint `auth`:**
- `/login`, `/logout`
- User store (`users.yaml`) read/write, password hashing, first-run admin
  seeding, `SECRET_KEY` bootstrap
- `require_login()` — registered via `app.before_request`, not
  `@auth_bp.before_request`, so it gates every blueprint, not just this one

**`nodemanager/nodes.py` — Blueprint `nodes`:**
- `/` - Dashboard with statistics
- `/nodes` - List all node configurations
- `/nodes/new` - Create new node form
- `/nodes/<name>` - View node details
- `/nodes/<name>/edit` - Edit node configuration
- `/nodes/<name>/logs` - Get node logs (JSON)
- `/nodes/<name>/delete`, `/nodes/bulk/delete` - Delete configuration(s)
- `/nodes/<name>/export` - Download config (.yaml or .zip with private key)
- `/nodes/import` - Import a config/backup

**`nodemanager/node_actions.py` — Blueprint `actions`:**
- `/nodes/<name>/start`, `/stop`, `/restart`
- `/nodes/bulk/start`, `/nodes/bulk/stop`
- Everything here talks to the Docker daemon to mutate container state;
  config-only mutations (delete) stay in `nodes.py` instead

**`nodemanager/api.py` — Blueprint `api`:**
- `/api/nodes` - List nodes (JSON)
- `/api/nodes/<name>/health` - Node health, from the server's own record
- `/api/nodes/<name>/tasks` - Task execution history
- `/api/server/version` - Look up a vantage6 server's version
- `/api/encryption/generate-key` - Generate an RSA key pair

**Shared helpers (not blueprints, imported by the above):**
- `nodemanager/docker_utils.py` - `get_docker_client()`, `get_running_nodes()`,
  `get_node_status()`, image lookup, volume/env construction
- `nodemanager/node_config.py` - `get_node_configs()` - reads all node YAML configs
- `nodemanager/server_api.py` - authenticates to the vantage6 server using a
  node's own `api_key` to fetch health/task history
- `nodemanager/crypto.py` - `generate_rsa_key_pair()`

Dependency direction is one-way: `config.py` ← the other util modules ←
the blueprints. `docker_utils.py` must never import from `server_api.py`
(the reverse dependency is the one real circular-import risk in this layout).

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
3. `nodemanager/nodes.py` (`new_node()`) validates input
4. Creates YAML config in `~/.config/vantage6/node/`
5. Redirects to node list with success message

### Starting a Node

1. User clicks start button
2. POST request to `/nodes/<name>/start`
3. `nodemanager/node_actions.py` (`start_node()`) reads node configuration
4. Uses Docker SDK to create/start container
5. Mounts config file and data volumes
6. Returns to node details page

### Viewing Logs

1. Browser loads node details page
2. JavaScript fetches `/nodes/<name>/logs`
3. `nodemanager/nodes.py` (`view_logs()`) queries Docker container logs
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
- Image: see [Node Docker Image](README.md#node-docker-image) in the README for how the image is
  resolved
- Volumes: config directory, data/vpn/ssh/squid volumes (see [docs/PATHS_AND_VOLUMES.md](docs/PATHS_AND_VOLUMES.md))
- Labels: `vantage6-type=node`, `name={name}`

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

See the README's [Authentication](README.md#authentication) and
[Security Considerations](README.md#security-considerations) sections for the current
auth/RBAC/audit-log model — it's the authoritative, up-to-date description.
