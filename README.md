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
- 🔐 **End-to-End Encryption**: Support for RSA-based encryption for secure communication
- ⚙️ **Advanced Options**: Manual Docker image override for custom deployments

## Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ (if running without Docker)
- Access to a Vantage6 server (version 4.x.x)

## Quick Start

### One-Command Install & Start (Fastest) 🚀

Download and start the Node Manager with a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/mdw-nl/vantage6-node-manager/main/start.sh | bash
```

**What this does:**
- ✅ Checks for Docker and Docker Compose
- ✅ Downloads all necessary files to `~/vantage6-node-manager`
- ✅ Creates required directories and `.env` file
- ✅ Pulls the latest pre-built Docker image and starts the application automatically

**Custom installation directory:**
```bash
curl -fsSL https://raw.githubusercontent.com/mdw-nl/vantage6-node-manager/main/start.sh | INSTALL_DIR=/path/to/custom/dir bash
```

**Access the application:**
Open your browser and navigate to `http://localhost:5000`

---

### Full Setup with Git Clone (Recommended for Development)

For a complete installation with git history:

```bash
curl -fsSL https://raw.githubusercontent.com/mdw-nl/vantage6-node-manager/main/setup.sh | bash -s -- --start
```

Or install without auto-starting:

```bash
curl -fsSL https://raw.githubusercontent.com/mdw-nl/vantage6-node-manager/main/setup.sh | bash
```

---

### Using Pre-built Docker Image (Advanced)

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
   - **Encryption** (optional): Enable end-to-end encryption and upload your private key
3. Click **Create Node Configuration**

#### Encryption Setup

Vantage6 supports end-to-end encryption to protect communication between nodes and ensure data privacy. When creating a node:

1. **Enable Encryption**: Check the "Enable Encryption" checkbox
2. **Choose Your Key Source**:
   
   **Option A: Generate New Key (Recommended for new organizations)**
   - Click the "Generate New Key" tab
   - Click "Generate New RSA Key Pair" button
   - The application will create a secure 4096-bit RSA key pair
   - Download your private key immediately using the "Download Private Key" button
   - The key will be automatically saved with your node configuration
   - **Important**: Share this downloaded key with all other nodes and users in your organization

   **Option B: Upload Existing Key (For existing organizations)**
   - Click the "Upload Existing Key" tab
   - Select your organization's RSA private key file (PEM format)
   - The key will be securely stored with your node configuration

3. **Important**: All nodes and users in your organization must use the same private key

**How it works:**
- All task inputs and results are encrypted using RSA keys
- The server cannot read encrypted communications
- Only your organization (with the private key) can decrypt messages
- A shared secret is used for symmetric encryption of the payload

**Key Security:**
- Private keys are stored securely in `~/.config/vantage6/node/private_keys/`
- Files are set to read-only permissions (0600) for the owner
- Back up your private key safely - losing it means you cannot decrypt existing messages
- Never share your private key with other organizations
- Generated keys use 4096-bit RSA for maximum security

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

1. **Flask Backend** (`app.py` + `nodemanager/`):
   - `app.py` — thin entrypoint: creates the Flask app, wires up auth, registers blueprints
   - `nodemanager/auth.py` — login/logout, user store, session auth gate
   - `nodemanager/nodes.py` — dashboard, node CRUD, view/logs/import/export
   - `nodemanager/node_actions.py` — start/stop/restart and bulk equivalents (Docker daemon mutations)
   - `nodemanager/api.py` — JSON `/api/*` endpoints
   - `nodemanager/docker_utils.py`, `node_config.py`, `server_api.py`, `crypto.py` — shared helpers (Docker client/containers, reading config YAML, talking to the vantage6 server, RSA key generation)

   See [ARCHITECTURE.md](ARCHITECTURE.md) for the full module breakdown.

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

The test suite covers the login/role/ownership enforcement boundary (`tests/test_permissions.py`,
`tests/test_ownership.py`) — not the full app. It's safe to run anytime: `tests/conftest.py` points
everything at a throwaway temp directory and resets it before every test, so it never touches your
running container, its real node configs, or `users.yaml`.

First time only, create the virtualenv and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

After that, from the repo root:

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Drop `-v` for a terser pass/fail summary, or target one file or test:

```bash
python -m pytest tests/test_ownership.py -v
python -m pytest tests/test_ownership.py::test_admin_delete_is_permanent -v
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

### Encryption Issues

**Problem**: "Encryption enabled but no private key file provided"

**Solution**:
- Ensure you've uploaded a valid private key file when creating the node
- The private key must be in PEM format
- Generate a new key pair if needed: `v6 node create-private-key`

**Problem**: Node fails to start with encryption errors

**Solution**:
- Verify the private key file exists and is readable
- Check that the private key matches the public key on the server
- Ensure all nodes in your organization use the same private key
- Verify the collaboration requires encryption (check with server admin)

**Problem**: Cannot decrypt task results

**Solution**:
- Confirm you're using the correct private key for your organization
- Verify the public key on the server matches your private key
- Check that other nodes in the collaboration have encryption enabled
- Ensure the private key hasn't been changed since results were encrypted

## Authentication

The web interface requires login. On first startup, if no `users.yaml` exists yet, an admin
account is created automatically:

- Set `ADMIN_USERNAME` / `ADMIN_PASSWORD` in your `.env` before the first `docker compose up` to
  choose your own credentials. **Blank `ADMIN_PASSWORD` again in `.env` once you've confirmed you
  can log in** — it's only read once to create the account, and leaving a real password sitting in
  a plaintext `.env` file is a needless risk (`.env` is world-readable by default; see
  [Security Considerations](#security-considerations)).
- If `ADMIN_PASSWORD` is left unset, a random password is generated and printed **once** to the
  container logs (`docker compose logs vantage6-node-manager`) — save it, it isn't shown again.

This seeding only happens once; restarting the container never resets an existing `users.yaml`.

### Roles and managing users

There are three roles:
- **admin** — reserved for the single account created automatically the first time the container
  starts (see above). Only this account can access **Users** to add/remove accounts, change
  roles, or reset passwords. It also has full node access. The admin role can't be granted to
  anyone else through the UI — `/users/new` and the role-change control only ever offer
  **operator** or **viewer**.
- **operator** — can create/edit/import/export nodes it has access to, and start/stop/restart
  them. "Delete" removes only itself from a node's access list rather than destroying it (see
  "Node ownership" below). Cannot access the Users page.
- **viewer** — same node-level access as operator, including "delete" meaning "leave," but can
  never start/stop/restart a container — on any node, including its own. That's the one thing
  distinguishing viewer from operator; both are otherwise scoped identically (see "Node ownership"
  below).

Log in as the admin account and go to **Users** in the sidebar to add operator/viewer accounts,
change a user's role between those two, reset a password, or delete a user. A few safeguards
refuse the action with a flash message rather than failing silently: the admin account can't be
deleted or demoted (there's always exactly one), and you can't delete or change the role of the
account you're currently logged in as.

### Node ownership

Each node an operator or viewer creates or imports belongs to that account — nobody else sees it
in the dashboard/node list, and direct links to it (view, edit, delete, export, and for operators
also start/stop/restart) behave as if it doesn't exist for them. The admin account always sees and
can manage every node regardless of who created it.

A node can have more than one owner — e.g. two people at the same organization both watching the
same physical node. Granting access isn't self-service: the account that creates a node becomes
its first owner automatically, but adding anyone else has to go through admin. On the Nodes page,
the admin account clicks the **Access** column for any node to open a checklist of every operator/
viewer account (admin itself is never in the list — it always has access regardless) and check/
uncheck who should have access, then saves the whole list in one go. Unchecking everyone makes the
node admin-only ("Admin only") rather than deleting it.

For anyone other than admin, **Delete just means "remove me"** — it takes the current user off
that node's access list and leaves everything else untouched: the config file, the running
container (if any), and every other owner's access all survive exactly as they were. This is true
even for the account that originally created the node — once a node might be shared, one person's
"delete" can't be allowed to destroy it out from under someone else who was granted access to it.
Deleting a user account works the same way: it removes them from every node's owner list rather
than leaving a dangling reference to a deleted account, and a node with other owners simply keeps
them. Only the **admin** account's delete is a real, permanent one — it removes the config file
itself (and its private key file too, if encryption was enabled, so nothing is left behind on
disk). If a node ends up with nobody left in its access list (its last owner left, or admin
deleted the last user who had access), it isn't gone — it just becomes admin-only, same as if
admin had unchecked everyone, and stays that way until admin reassigns or permanently deletes it.

Nothing is visible by default just because nobody owns it yet: a node with no recorded owner —
whether it predates this feature, was created by admin, or had every owner removed/leave — is
visible only to admin, not shared with every operator/viewer.

Two nodes can never share a name, and two nodes can never share an API key either — creating,
importing, *or editing* a node rejects both, with a message pointing at asking admin for access
instead. (An edit is always allowed to keep the node's own existing API key — the check only
blocks taking on someone *else's*.) The name check exists because the node's local name doubles as
its Docker container name; the API key check exists because the API key is the node's actual
identity on the real vantage6 server, so two separately-run containers authenticating with the
same key would conflict there. If you want access to a node someone else already added, ask admin
to add you as an owner — don't try to recreate it under a different name.

The edit page also shows a heads-up banner whenever a node has other owners besides you, naming
them — connection/database/encryption changes apply to the node itself, so anyone else who has
access sees them too, not just a copy in your own view.

### Activity log

Admin has an **Activity Log** page (linked in the sidebar) recording who did what, and when, to
nodes and user accounts: creating/editing/importing/deleting a node, leaving one, granting or
revoking access, starting/stopping/restarting a container, creating/deleting a user or changing
their role or password, and every login attempt — successful or failed, including the username
typed on a failed one (even if it doesn't belong to a real account, so a scan/guessing attempt
still shows up). Each entry records the timestamp (UTC), the acting account and its role, the
action, and whichever node and/or target user it applied to. The page shows the most recent 300
events; the **Download CSV** button on that page exports the complete history for anyone who needs
to keep or search further back than that.

Because a failed login's username is recorded exactly as typed rather than checked against
anything, the CSV export defends against formula injection: a value starting with `=`, `+`, `-`,
`@`, tab, or carriage return is prefixed with a `'` before being written out, so opening the
export in Excel/Sheets can't be tricked into evaluating an attacker-typed "username" as a formula.

This is a plain, append-only log (`audit.log`, stored alongside `users.yaml` and
`node_owners.yaml`) rather than a full tamper-evident audit trail — good enough to answer "who
changed this node's config last week," not a compliance-grade record.

### Where the account is stored

Credentials live in `users.yaml`, next to this app's other persistent state (node configs,
private keys) at `~/.config/vantage6/` **on the machine running the container** — not inside this
repository. That's deliberate: this project directory is source code that gets built into the
Docker image, so anything placed here would either get wiped on a fresh clone/rebuild, or — worse
— get baked into the image itself and shipped to anyone who pulls it from the registry. Every
person running their own instance gets their own `users.yaml` under their own home directory, the
same way each of you already has your own node configs and private keys there.

Because the container runs as root, the file is created as `root`-owned with `600` permissions
(readable only by root), so you can't just `cat` it directly as your normal user. Two ways in:

```bash
# Via the running container (no sudo needed):
docker compose exec vantage6-node-manager cat /root/.config/vantage6/users.yaml

# Or directly on the host:
sudo cat ~/.config/vantage6/users.yaml
```

### Resetting or changing the password

If you're locked out of an *individual* account but another admin can still log in, use the
**Users** page instead of anything below — an admin can reset any user's password from there
in a couple of clicks, and it's the normal path now that there can be more than one account.

The steps below are for when there's no working admin account at all. The seeding step only runs
when `users.yaml` doesn't exist yet, so resetting means deleting it and letting the app recreate
it — **this wipes every account in the file, not just the admin one**, since multi-user support
means `users.yaml` may hold several accounts by now.
```bash
# 1. set the new password in .env (or leave ADMIN_PASSWORD blank to get a generated one)
# 2. delete the existing account
docker compose exec vantage6-node-manager rm /root/.config/vantage6/users.yaml
# 3. recreate the container so it picks up the new .env value and reseeds
docker compose up -d
# 4. if you set your own password, blank ADMIN_PASSWORD in .env again now that it's seeded
```

Alternatively, edit the password hash in place without touching `.env` or restarting anything:
```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('newpassword'))"
# then, as root (sudo or `docker compose exec ... vi ...`), replace the matching
# password_hash value in users.yaml with the output above
```

## Security Considerations

- **Change the default SECRET_KEY** in production (a random one is auto-generated and persisted
  if you don't set one, but setting your own is still recommended)
- Store sensitive information (API keys) securely
- **Protect your private keys**: Never share them with other organizations
- Back up private keys securely - losing them means losing access to encrypted data
- Use HTTPS in production environments
- Restrict Docker socket access appropriately
- Regularly rotate API keys and encryption keys according to your security policy

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

## Branding

This application features the [Medical Data Works](https://www.medicaldataworks.nl) corporate branding:
- Custom color scheme based on MDW brand guidelines
- MDW logo and styling throughout the interface
- Professional, accessible design for healthcare/research environments

For more information about the branding implementation, see [docs/BRANDING.md](docs/BRANDING.md).

## Acknowledgments

- Developed by [Medical Data Works](https://www.medicaldataworks.nl) - Research data made accessible
- Built for [Vantage6](https://vantage6.ai/) - Privacy-preserving Federated Learning infrastructure
- Uses Bootstrap 5 for UI components
- Powered by Flask and Docker

## Roadmap

Future enhancements:
- [x] User authentication and authorization
- [x] Multi-user support with role-based access
- [x] Advanced log filtering and search
- [x] Node health monitoring
- [ ] Health alerts / notifications
- [x] Backup and restore configurations
- [ ] Algorithm store integration
- [x] Task execution monitoring
- [ ] WebSocket support for real-time updates
- [x] Export/import node configurations
- [x] Batch operations on multiple nodes
- [x] Edit nodes configs