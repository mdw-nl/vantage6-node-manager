# Node Configuration and Database URI Environment Variables Fix

## Problem

After fixing the main container startup issues, node containers were still failing with two errors:

### Error 1: Invalid Logging Configuration
```
AssertionError: Invalid value '{'file': 'um.log', 'level': 'INFO'}' provided for field 'logging'
```

### Error 2: Missing Database URI Environment Variable
```
KeyError: 'DEFAULT_DATABASE_URI'
```

## Root Causes

### 1. Incomplete Logging Configuration

The node configuration file had a minimal logging configuration:
```yaml
logging:
  file: um.log
  level: INFO
```

However, vantage6's `NodeConfiguration` validator requires a complete logging configuration with all fields:
```python
LOGGING_VALIDATORS = {
    "level": Use(str),
    "use_console": Use(bool),
    "backup_count": And(Use(int), lambda n: n > 0),
    "max_size": And(Use(int), lambda b: b > 16),
    "format": Use(str),
    "datefmt": Use(str),
}
```

### 2. Missing Database URI Environment Variables

When running in dockerized mode, the vantage6 node expects database URIs to be passed as environment variables in the format `<LABEL>_DATABASE_URI`. This is required because:

1. The node container needs to know database locations
2. Database paths may need conversion from container paths to host paths
3. Environment variables allow the node to properly configure database connections

From `vantage6-node/vantage6/node/docker/docker_manager.py` line 209:
```python
uri = os.environ[f"{label_upper}_DATABASE_URI"]
```

## Solutions

### Solution 1: Fix Logging Configuration

Updated the node configuration file (`~/.config/vantage6/node/um.yaml`) with complete logging configuration:

```yaml
logging:
  backup_count: 5
  datefmt: '%Y-%m-%d %H:%M:%S'
  file: um.log
  format: '%(asctime)s - %(name)-14s - %(levelname)-8s - %(message)s'
  level: INFO
  max_size: 1024
  use_console: true
  loggers:
  - level: warning
    name: urllib3
  - level: warning
    name: requests
  - level: warning
    name: engineio.client
  - level: warning
    name: docker.utils.config
  - level: warning
    name: docker.auth
```

This matches the template structure in `vantage6/cli/template/node_config.j2`.

### Solution 2: Add Database URI Environment Variables

Updated `app.py` `start_node()` function to add database URIs as environment variables:

```python
# Add database URIs as environment variables (required for dockerized nodes)
# The node expects <LABEL>_DATABASE_URI environment variables
if config['data'].get('databases'):
    for db in config['data'].get('databases'):
        label = db.get('label', '').upper()
        uri = db.get('uri', '')
        if label and uri:
            env[f'{label}_DATABASE_URI'] = uri
```

This ensures that for each database defined in the node configuration, the corresponding environment variable is set. For example:
- Database label: `default` → Environment variable: `DEFAULT_DATABASE_URI`
- Database label: `patient_data` → Environment variable: `PATIENT_DATA_DATABASE_URI`

## Testing

After applying both fixes:

1. **Logging Configuration** ✅:
   ```
   2025-10-28 20:48:54 - context        - INFO     - Successfully loaded configuration from '/mnt/config/um.yaml'
   2025-10-28 20:48:54 - context        - INFO     - Logging to '/mnt/log/node_user.log'
   ```

2. **Node Initialization** ✅:
   ```
   2025-10-28 20:48:54 - node           - INFO     - Connecting server: http://host.docker.internal:7601/api
   2025-10-28 20:48:54 - common         - INFO     - Successfully authenticated
   2025-10-28 20:48:54 - node           - INFO     - Node name: better - Maastricht University
   ```

The node now progresses past initialization and successfully authenticates with the server!

## Required Node Configuration Structure

For reference, here's the complete minimal node configuration structure that passes validation:

```yaml
api_key: <your-api-key>
api_path: /api
databases:
  - label: <label>
    type: <csv|sparql|sql|parquet|excel|other>
    uri: <database-uri-or-path>
encryption:
  enabled: false
  private_key: null
logging:
  backup_count: 5
  datefmt: '%Y-%m-%d %H:%M:%S'
  file: <filename>.log
  format: '%(asctime)s - %(name)-14s - %(levelname)-8s - %(message)s'
  level: <DEBUG|INFO|WARNING|ERROR|CRITICAL>
  max_size: 1024
  use_console: true
  loggers:
    - level: warning
      name: urllib3
    - level: warning
      name: requests
    - level: warning
      name: engineio.client
    - level: warning
      name: docker.utils.config
    - level: warning
      name: docker.auth
port: <server-port>
server_url: <server-url>
task_dir: /tmp/vantage6
```

## Files Changed

1. **`~/.config/vantage6/node/um.yaml`** - Updated with complete logging configuration
2. **`app.py`** (lines 581-594) - Added database URI environment variables

## Next Steps

To start the node:
1. Remove old container: `docker stop vantage6-um-user && docker rm vantage6-um-user`
2. Start through Node Manager web UI at `http://localhost:5000/nodes/um`
3. Or use `v6 node start --name um` command

The node should now start successfully and connect to the server!

## Key Takeaways

1. **Configuration Validation**: Vantage6 uses strict schema validation - all required fields must be present
2. **Dockerized Mode**: Requires environment variables for database URIs, not file paths
3. **Logging Structure**: Must include all fields (backup_count, max_size, format, datefmt, use_console, loggers)
4. **Configuration Templates**: Always refer to official templates in `vantage6/cli/template/` for correct structure
