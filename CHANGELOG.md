# Changelog

All notable changes to the Vantage6 Node Manager project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Multi-user support with role-based access control (admin/operator/viewer), per-node ownership
  and sharing, and an admin-only Activity Log — see the README's
  [Authentication](README.md#authentication) section for the full model
- Per-node Docker image override (the **Node Image** field on Create/Edit Node), plus a pinned
  known-good default — see [Node Docker Image](README.md#node-docker-image)
- End-to-end encryption support: web-based RSA key pair generation (4096-bit), private key
  upload, and encrypted node communication
- Medical Data Works corporate branding (see [docs/BRANDING.md](docs/BRANDING.md))
- GitHub Actions CI/CD: automated Docker builds/publishing to GHCR, image testing, Trivy
  vulnerability scanning, Hadolint linting (see [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md))
- `start.sh` - one-command install & start script for deployments that don't need a git clone
- Export/import of node configurations, batch start/stop across multiple nodes

### Changed
- Node container creation now matches the official vantage6 CLI's layout: dedicated data/vpn/ssh/
  squid Docker volumes, a mounted config directory, and the `vnode-local start` command, instead
  of a minimal setup that caused containers to exit immediately
- Automatic "detect server version → pick matching image" behavior was replaced with a pinned
  default image plus an explicit per-node override, since node image tags and server version
  strings don't line up 1:1 and can't be derived from each other reliably
- Node image registry moved from the now-dead `harbor2.vantage6.ai` to
  `ghcr.io/mdw-nl/vantage6/infrastructure/node-lite`
- Config/data/log paths are now driven by environment variables instead of `Path.home()`, for
  predictable behavior inside containers
- Restart now fully recreates the node's container (stop, remove, recreate from the current
  config) instead of a plain container restart, so config edits apply without a manual Stop/Start

## [1.0.0] - 2025-10-19

### Added - Initial Release

#### Core Features
- Web-based dashboard for managing Vantage6 nodes
- Node configuration creation via web form
- Start/Stop/Restart node operations
- Real-time node status monitoring
- Container log viewing with auto-refresh
- Delete node configurations
- Multi-node support (user and system configurations)

#### User Interface
- Responsive Bootstrap 5-based UI
- Dashboard with statistics cards
- Node list view with filtering
- Node detail view with logs
- Create node form with validation
- Navigation sidebar
- Flash message system for user feedback

#### Backend
- Flask 3.0.0 web framework
- Docker SDK integration for container management
- YAML configuration file parsing
- RESTful API endpoints
- Error handling and validation

#### Docker Support
- Dockerfile for containerized deployment
- docker-compose.yml for easy orchestration
- Health check configuration
- Volume mounting for configs and data
- Docker socket access for container management

#### Configuration
- Environment variable support (.env)
- .gitignore for version control
- Example configurations

#### API Endpoints
- `GET /` - Dashboard
- `GET /nodes` - List all nodes
- `GET /nodes/new` - Create node form
- `POST /nodes/new` - Create node
- `GET /nodes/<name>` - View node details
- `POST /nodes/<name>/start` - Start node
- `POST /nodes/<name>/stop` - Stop node
- `POST /nodes/<name>/restart` - Restart node
- `POST /nodes/<name>/delete` - Delete node
- `GET /nodes/<name>/logs` - Get logs (JSON)
- `GET /api/nodes` - API: List nodes
- `GET /api/nodes/<name>/status` - API: Get status

### Technical Details

#### Dependencies
- Flask==3.0.0
- PyYAML==6.0.1
- docker==7.0.0
- Werkzeug==3.0.1

#### Compatibility
- Python 3.11+
- Vantage6 4.x.x
- Docker Engine 20.10+
- Docker Compose 2.0+

#### Supported Platforms
- Linux (tested)
- macOS (tested)
- Windows (should work with Docker Desktop)

### Known Limitations (at the time of this release)

- No built-in authentication (added later — see Unreleased above)
- Configuration editing required manual YAML editing (added later — see Unreleased above)
- Single-user mode only (added later — see Unreleased above)
- No task execution monitoring (view only)
- No algorithm store integration

### Security Notes (at the time of this release)

- Generates random SECRET_KEY during setup
- API keys stored in YAML files (not encrypted)
- Requires Docker socket access
- No TLS/HTTPS support (use reverse proxy)

---

## Version History

| Version | Date       | Description           |
|---------|------------|-----------------------|
| 1.0.0   | 2025-10-19 | Initial release      |

---

## Contributors

- Initial development: Built based on Vantage6 CLI analysis

## License

[To be determined]

---

For more information, see:
- [README.md](README.md) - Full documentation
- [GitHub Issues](../../issues) - Report bugs or request features
