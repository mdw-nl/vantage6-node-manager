# Production Deployment - Quick Reference

## Summary of Path Fixes

This document summarizes the fixes made to ensure proper path handling in production Docker environments.

## Changes Made

### 1. Application Code (`app.py`)

#### Path Conversion Function (CRITICAL FIX)
Added `container_path_to_host_path()` function to convert container paths to host paths:

```python
def container_path_to_host_path(container_path):
    """
    Convert a path inside the Node Manager container to the corresponding host path.
    This is needed when the Node Manager creates volumes for node containers.
    """
    # Converts:
    # /root/.config/vantage6/... -> ${HOME}/.config/vantage6/...
    # /etc/vantage6/node/...     -> ${HOME}/.config/vantage6-system/...
    # /data/...                  -> ${HOME}/vantage6-data/...
```

**Why this is critical**: When Node Manager runs in Docker and creates node containers, it must mount volumes using **host paths**, not its own container paths. Without this conversion, Docker throws "path is not shared from the host" errors.

#### Environment Variable Support
```python
# OLD - Used Path.home() which could be unpredictable in containers
VANTAGE6_CONFIG_DIR = Path.home() / '.config' / 'vantage6' / 'node'

# NEW - Uses environment variables with sensible defaults
VANTAGE6_CONFIG_DIR = Path(os.environ.get('VANTAGE6_CONFIG_DIR', '/root/.config/vantage6/node'))
VANTAGE6_SYSTEM_CONFIG_DIR = Path(os.environ.get('VANTAGE6_SYSTEM_CONFIG_DIR', '/etc/vantage6/node'))
VANTAGE6_DATA_DIR = Path(os.environ.get('VANTAGE6_DATA_DIR', '/data'))
```

#### Task Directory
```python
# OLD - Used ephemeral /tmp directory
task_dir = request.form.get('task_dir', '/tmp/vantage6')

# NEW - Uses persistent mounted volume
task_dir = request.form.get('task_dir', '/mnt/data/tasks')
```

#### Database Mounting Logic
Enhanced to handle three scenarios:
1. **Absolute paths in mounted volumes** (e.g., `/data/mydata.csv`)
2. **Relative paths** (assumes relative to `VANTAGE6_DATA_DIR`)
3. **Host paths** (attempts to resolve and warns if not found)

The new logic:
- Checks if path exists and is accessible
- Handles paths already in `/data/` directory
- Attempts to find files by name in data directory
- Provides helpful warning messages when files aren't found

### 2. Docker Configuration

#### Dockerfile
Added environment variables:
```dockerfile
ENV VANTAGE6_CONFIG_DIR=/root/.config/vantage6/node
ENV VANTAGE6_SYSTEM_CONFIG_DIR=/etc/vantage6/node
ENV VANTAGE6_DATA_DIR=/data
```

Created all necessary directories:
```dockerfile
RUN mkdir -p /root/.config/vantage6/node && \
    mkdir -p /etc/vantage6/node && \
    mkdir -p /data
```

#### docker-compose.yml & docker-compose.prod.yml
Added system config mount:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - ${HOME}/.config/vantage6:/root/.config/vantage6
  - ${HOME}/.config/vantage6-system:/etc/vantage6/node  # NEW
  - ${HOME}/vantage6-data:/data
```

Added environment variables:
```yaml
environment:
  - VANTAGE6_CONFIG_DIR=/root/.config/vantage6/node
  - VANTAGE6_SYSTEM_CONFIG_DIR=/etc/vantage6/node
  - VANTAGE6_DATA_DIR=/data
```

## Migration Guide

### For Existing Deployments

1. **Update your deployment**:
   ```bash
   docker-compose down
   docker-compose pull  # If using pre-built image
   docker-compose up -d
   ```

2. **Create system config directory** (if needed):
   ```bash
   mkdir -p ~/.config/vantage6-system
   ```

3. **Move data files to the data directory**:
   ```bash
   mkdir -p ~/vantage6-data
   cp /path/to/your/data/*.csv ~/vantage6-data/
   ```

4. **Update node configurations**:
   - Edit YAML files in `~/.config/vantage6/node/`
   - Change database URIs to use `/data/` prefix:
     ```yaml
     databases:
       - uri: /data/mydata.csv  # Updated path
     ```

### For New Deployments

Simply use the updated `docker-compose.prod.yml`:
```bash
docker-compose -f docker-compose.prod.yml up -d
```

All paths will work correctly out of the box.

## Verification Steps

### 1. Check Volume Mounts
```bash
docker inspect vantage6-node-manager | grep -A 10 Mounts
```

Expected output should include:
- `/var/run/docker.sock`
- `/.config/vantage6`
- `/.config/vantage6-system`
- `/vantage6-data`

### 2. Check Environment Variables
```bash
docker exec vantage6-node-manager env | grep VANTAGE6
```

Expected output:
```
VANTAGE6_CONFIG_DIR=/root/.config/vantage6/node
VANTAGE6_SYSTEM_CONFIG_DIR=/etc/vantage6/node
VANTAGE6_DATA_DIR=/data
```

### 3. Verify Directory Creation
```bash
docker exec vantage6-node-manager ls -la /root/.config/vantage6/
docker exec vantage6-node-manager ls -la /etc/vantage6/
docker exec vantage6-node-manager ls -la /data/
```

### 4. Test Database File Access
```bash
# Place a test file
echo "test" > ~/vantage6-data/test.csv

# Check it's visible in container
docker exec vantage6-node-manager ls -la /data/test.csv
```

## Benefits

### Before
❌ Config paths used `Path.home()` - unpredictable in containers  
❌ Database files couldn't be found when Node Manager ran in container  
❌ Task outputs stored in `/tmp` - lost on restart  
❌ System configs had no mount point  
❌ No flexibility to customize paths  

### After
✅ Explicit environment-variable-based paths  
✅ Intelligent database file resolution with warnings  
✅ Persistent task output directory  
✅ System config directory properly mounted  
✅ Full flexibility via environment variables  
✅ Works seamlessly in production Docker environments  

## Troubleshooting

### Issue: "Database file not found" warning
**Solution**: Ensure file exists at `${HOME}/vantage6-data/yourfile.csv` on host

### Issue: Config not persisting
**Solution**: Check volume mount with `docker inspect vantage6-node-manager`

### Issue: Permission denied
**Solution**: Check file permissions - container runs as root

### Issue: Node container can't access data
**Solution**: Verify database path in config uses `/data/` prefix

## Documentation

For detailed information, see:
- **[docs/PATHS_AND_VOLUMES.md](PATHS_AND_VOLUMES.md)** - Complete path mapping guide
- **[CHANGELOG.md](../CHANGELOG.md)** - All changes documented
- **[README.md](../README.md)** - Quick start guide

## Testing

To test the fixes:

1. Start the Node Manager
2. Create a test data file: `echo "col1,col2" > ~/vantage6-data/test.csv`
3. Create a node via web UI with database URI: `/data/test.csv`
4. Start the node
5. Check logs - should not show "file not found" errors

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review logs: `docker logs vantage6-node-manager`
3. Verify all volume mounts are active
4. Ensure environment variables are set correctly
