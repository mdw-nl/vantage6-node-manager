# Changelog

All notable changes to the Vantage6 Node Manager project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed - CRITICAL
- **Node Container Startup**: Fixed containers exiting immediately after creation
  - Added missing `command` parameter (`vnode-local start --name ... --config ... --dockerized`)
  - Created required Docker volumes (data, vpn, ssh, squid) per official implementation
  - Fixed volume mount structure to match official vantage6 CLI
  - Added required environment variables (DATA_VOLUME_NAME, VPN_VOLUME_NAME, etc.)
  - Enabled TTY mode for proper container I/O
  - Mounted config directory instead of single config file
  - Documentation in `docs/VANTAGE6_OFFICIAL_ALIGNMENT.md`
- **Database URI Environment Variables**: Added database URI environment variables for dockerized nodes
  - Node expects `<LABEL>_DATABASE_URI` environment variables when running in dockerized mode
  - Automatically sets environment variables for all configured databases
  - Fixes `KeyError: 'DEFAULT_DATABASE_URI'` error
  - Documentation in `docs/DATABASE_URI_FIX.md`
- **Node Configuration Logging**: Updated node configuration creation to include complete logging structure
  - Now includes all required fields: backup_count, datefmt, format, max_size, use_console, loggers
  - Prevents "Invalid value provided for field 'logging'" validation errors
  - Matches official vantage6 node configuration template structure

### Added
- **Medical Data Works Branding**: Complete corporate branding integration
  - Custom MDW color scheme (#00adef primary, #51bcda secondary, #66615b text)
  - MDW logo in navbar
  - Custom CSS theme file (`static/mdw-theme.css`)
  - Updated footer with MDW attribution
  - Professional healthcare/research environment styling
  - Branding documentation in `docs/BRANDING.md`
- **Production Path Configuration**: Comprehensive path and volume management
  - Environment variable support for all directory paths
  - System config directory mount (`/etc/vantage6/node`)
  - Data directory environment variable (`VANTAGE6_DATA_DIR`)
  - Documentation for path mappings in production (`docs/PATHS_AND_VOLUMES.md`)
- **Docker Volume Management**: Automatic creation of persistent volumes
  - Data volume for task data and results
  - VPN volume for VPN configuration
  - SSH volume for SSH tunnel configuration
  - Squid volume for proxy configuration

### Changed
- Updated navbar to light theme with MDW logo
- Replaced default colors with MDW brand colors throughout
- Updated stats cards on dashboard with MDW color gradient
- Modified Dockerfile to include static assets
- **Path Configuration Improvements**:
  - Config directories now use environment variables instead of `Path.home()`
- **Volume Mounting Strategy**:
  - Changed `/mnt/data` from bind mount to Docker volume
  - Mount config directory instead of individual config files
  - Use volume names for VPN, SSH, and Squid instead of bind mounts
  - Default task directory changed from `/tmp/vantage6` to `/mnt/data/tasks` for persistence
  - Database mounting logic improved to handle container environments correctly
  - Added intelligent path resolution for database files (absolute, relative, and mounted paths)
  - Added warning messages when database files are not found

### Fixed
- **Production Docker Path Issues**:
  - Fixed database file mounting when Node Manager runs in container
  - Resolved config directory path issues in containerized environments
  - Fixed ephemeral task directory using `/tmp` (now uses persistent mounted volume)
  - Added system config directory volume mount to docker-compose files
  - Corrected path handling for database files in various mount scenarios
  - **Critical Fix**: Node Manager now converts container paths to host paths when creating node containers
    - Prevents "path is not shared from the host" Docker errors
    - Enables proper volume mounting from containerized Node Manager to node containers
    - Adds `container_path_to_host_path()` helper function for path translation

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

#### Documentation
- README.md - Comprehensive project documentation
- GETTING_STARTED.md - Quick start guide
- ARCHITECTURE.md - Technical architecture details
- QUICK_REFERENCE.md - Command and API reference
- PROJECT_SUMMARY.md - Project overview
- UI_GUIDE.md - User interface mockups and design
- CHANGELOG.md - Version history

#### Configuration
- Environment variable support (.env)
- Automated setup script (setup.sh)
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

### Known Limitations

- No built-in authentication (planned for v2.0)
- Configuration editing requires manual YAML editing
- Single-user mode only
- No task execution monitoring (view only)
- No algorithm store integration

### Security Notes

- Generates random SECRET_KEY during setup
- API keys stored in YAML files (not encrypted)
- Requires Docker socket access
- No TLS/HTTPS support (use reverse proxy)

---

## [Unreleased]

### Added
- **Automatic server version detection** via `/api/version` endpoint
- Dynamic node image selection based on detected server version
- Server version display in node details page with live check
- Advanced start modal for manual Docker image override
- New API endpoint `/api/server/version` to check Vantage6 server versions
- Real-time server version checking with visual feedback
- Recommended Docker image displayed based on server version
- **End-to-end encryption support**:
  - Encryption enable/disable toggle in node creation form
  - **Web-based RSA key pair generation** (4096-bit keys)
  - One-click private key generation without CLI knowledge
  - Private key download functionality
  - Public key viewing modal
  - Private key file upload functionality (for existing keys)
  - Secure private key storage with proper permissions (0600)
  - Encryption status display in node list and detail views
  - Private key path configuration in node YAML files
  - Detailed encryption information and help text
  - Encryption troubleshooting documentation
  - API endpoint for key generation (`/api/encryption/generate-key`)
- **GitHub Actions CI/CD workflows**:
  - `docker-build.yml` - Automated Docker image builds and publishing to GHCR
  - `docker-test.yml` - Docker image testing, linting, and security scanning
  - `release.yml` - Release workflow for publishing to GHCR
- Multi-platform Docker image support (amd64, arm64)
- Automated vulnerability scanning with Trivy
- Dockerfile linting with Hadolint
- Build cache for faster CI/CD builds
- Supply chain security with build attestations
- Pre-built Docker images available at `ghcr.io/mdw-nl/vantage6-node-manager`
- Production docker-compose configuration (`docker-compose.prod.yml`)
- Comprehensive GitHub Actions documentation (`GITHUB_ACTIONS.md`)

### Changed
- Security scan workflow now gracefully handles repositories without GitHub Advanced Security enabled
- Trivy scan results displayed in workflow logs even when SARIF upload fails

### Fixed
- GitHub Actions security-scan job no longer fails on private repos without Advanced Security
- Node starting now auto-detects server version instead of using hard-coded version
- Start button now includes "Auto-detect Version" indication
- Added `requests` library to dependencies for HTTP requests

### Technical
- Added `get_server_version()` function to query server version endpoint
- Added `get_node_image_for_version()` function to determine appropriate image
- Enhanced error handling for server connection issues
- Added timeout handling for version detection requests

---

## [Unreleased] - Future Plans

### Planned for v2.0
- [ ] User authentication and login system
- [ ] Multi-user support with RBAC
- [ ] Web-based configuration editor
- [ ] Task execution monitoring
- [ ] Algorithm store integration
- [ ] Advanced log filtering and search
- [ ] Email/webhook notifications
- [ ] Backup/restore configurations
- [ ] HTTPS support
- [ ] Database encryption

### Planned for v1.1
- [ ] Unit tests
- [ ] Integration tests
- [ ] CI/CD pipeline
- [ ] Performance optimizations
- [ ] WebSocket support for real-time updates
- [ ] Export/import node configurations
- [ ] Batch operations on multiple nodes

### Under Consideration
- [ ] Prometheus metrics export
- [ ] Grafana dashboard integration
- [ ] Node health monitoring and alerts
- [ ] Configuration version control
- [ ] Audit logging
- [ ] API rate limiting
- [ ] Mobile app
- [ ] Dark mode theme

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
- [GETTING_STARTED.md](GETTING_STARTED.md) - Quick start
- [GitHub Issues](../../issues) - Report bugs or request features
