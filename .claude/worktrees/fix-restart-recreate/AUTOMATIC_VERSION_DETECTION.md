# Automatic Version Detection - Feature Documentation

## Overview

The Vantage6 Node Manager now automatically detects the server version and uses the appropriate node Docker image, eliminating the need for hard-coded versions.

## How It Works

### 1. Server Version Detection

When you start a node, the application:
1. Reads the server URL from the node configuration
2. Makes an HTTP request to `<server_url><api_path>/version`
3. Parses the version from the JSON response
4. Determines the appropriate node Docker image
5. Starts the node container with the matching version

### 2. Version Endpoint

The application queries the Vantage6 server's version endpoint:

```
GET https://your-server.com/api/version
```

Expected response format:
```json
{
  "version": "4.7.1"
}
```

or

```json
{
  "v": "4.7.1"
}
```

### 3. Image Selection

Based on the detected version, the application selects:
```
harbor2.vantage6.ai/infrastructure/node:<detected_version>
```

For example:
- Server version `4.7.1` → Node image `harbor2.vantage6.ai/infrastructure/node:4.7.1`
- Server version `4.6.0` → Node image `harbor2.vantage6.ai/infrastructure/node:4.6.0`

## User Interface Changes

### Node Details Page

**New Features:**
- **Server Version Badge**: Displays the detected server version with color coding:
  - 🟢 Green: Version successfully detected
  - 🟡 Yellow: Unable to detect version
  - 🔴 Red: Error during detection
  
- **Refresh Button**: Manually re-check server version

- **Advanced Start Modal**: 
  - Click "Advanced Start" for manual image override
  - Default behavior auto-detects version
  - Option to specify custom Docker image

### Start Button Behavior

**Before:**
- Hard-coded to `harbor2.vantage6.ai/infrastructure/node:4.7.1`

**Now:**
- Primary button: "Start Node (Auto-detect Version)"
  - Automatically queries server
  - Uses matching node version
  - Shows info message with detected version
  
- Advanced button: "Advanced Start"
  - Opens modal for manual configuration
  - Allows custom Docker image specification
  - Bypasses auto-detection if image provided

## API Endpoints

### New Endpoint: Check Server Version

```bash
GET /api/server/version?server_url=<url>&api_path=<path>
```

**Parameters:**
- `server_url` (required): Full URL of the Vantage6 server
- `api_path` (optional): API path, defaults to `/api`

**Example Request:**
```bash
curl "http://localhost:5000/api/server/version?server_url=https://server.vantage6.ai&api_path=/api"
```

**Success Response:**
```json
{
  "success": true,
  "version": "4.7.1",
  "server_url": "https://server.vantage6.ai",
  "recommended_image": "harbor2.vantage6.ai/infrastructure/node:4.7.1"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Could not connect to server at https://server.vantage6.ai",
  "server_url": "https://server.vantage6.ai"
}
```

## Error Handling

The application gracefully handles various error scenarios:

### Connection Errors
- **Scenario**: Server is unreachable
- **Behavior**: Falls back to `latest` tag, shows warning message
- **User Action**: Check server URL and network connectivity

### Timeout Errors
- **Scenario**: Server response takes too long (>5 seconds)
- **Behavior**: Falls back to `latest` tag, shows timeout warning
- **User Action**: Check server performance or use manual override

### Version Parse Errors
- **Scenario**: Server returns unexpected response format
- **Behavior**: Falls back to `latest` tag, shows parse error
- **User Action**: Use "Advanced Start" to manually specify image

### Missing Server URL
- **Scenario**: Node configuration lacks server URL
- **Behavior**: Falls back to `latest` tag, shows configuration warning
- **User Action**: Update node configuration with valid server URL

## Benefits

1. **No Manual Version Management**: Automatically stays in sync with server
2. **Reduced Configuration Errors**: No version mismatches
3. **Easier Upgrades**: Server upgrades automatically trigger correct node version
4. **Better Compatibility**: Ensures node and server versions match
5. **Flexibility**: Advanced users can still override if needed

## Technical Implementation

### New Dependencies

Added to `requirements.txt`:
```
requests==2.31.0
```

### New Functions in `app.py`

1. **`get_server_version(server_url, api_path)`**
   - Queries server version endpoint
   - Returns (version, error) tuple
   - Handles timeouts, connection errors, HTTP errors
   
2. **`get_node_image_for_version(version)`**
   - Constructs Docker image name from version
   - Handles various version formats
   - Returns full image path with tag

3. **Updated `start_node(name)`**
   - Checks for manual image override
   - Calls `get_server_version()` if no override
   - Uses detected version or falls back to `latest`
   - Displays appropriate flash messages

### JavaScript Enhancement

Added to `view_node.html`:
```javascript
function checkServerVersion() {
  // Fetches server version via API
  // Updates badge with result
  // Shows color-coded status
}
```

## Migration Guide

### For Existing Deployments

No configuration changes required! The system works with existing node configurations.

**What happens on upgrade:**
1. Pull latest code
2. Rebuild Docker image: `docker-compose build`
3. Restart application: `docker-compose up -d`
4. Existing nodes continue working
5. Next start will use auto-detection

### For New Deployments

Follow standard installation:
```bash
./setup.sh
docker-compose up -d
```

Version detection works automatically.

## Troubleshooting

### Issue: Version shows "Unable to detect"

**Causes:**
- Server is not accessible
- Server URL is incorrect
- Server doesn't have `/api/version` endpoint
- Network connectivity issues

**Solutions:**
1. Verify server URL in node configuration
2. Test server access: `curl https://your-server.com/api/version`
3. Check network connectivity
4. Use "Advanced Start" to manually specify image

### Issue: Wrong node version used

**Causes:**
- Server version endpoint returns incorrect version
- Caching issues

**Solutions:**
1. Click refresh button next to server version
2. Check server's actual version
3. Use "Advanced Start" with specific image version

### Issue: "latest" tag used instead of specific version

**Causes:**
- Auto-detection failed
- Server URL not configured

**Solutions:**
1. Check application logs for error details
2. Verify server configuration
3. Use "Advanced Start" for manual override

## Future Enhancements

Potential improvements for future versions:

- [ ] Cache server versions to reduce API calls
- [ ] Support for pre-release/beta versions
- [ ] Configurable fallback behavior (latest vs specific version)
- [ ] Version compatibility warnings
- [ ] Bulk version check for multiple nodes
- [ ] Version history tracking
- [ ] Automatic node updates when server upgrades

## Testing

### Manual Testing Steps

1. **Test Auto-Detection:**
   - Create a node configuration
   - Navigate to node details
   - Observe server version badge (should show version)
   - Click "Start Node"
   - Verify correct image is used in flash message

2. **Test Advanced Start:**
   - Click "Advanced Start"
   - Leave image field empty (auto-detect)
   - Start node
   - Verify version detection worked

3. **Test Manual Override:**
   - Click "Advanced Start"
   - Enter custom image: `harbor2.vantage6.ai/infrastructure/node:4.6.0`
   - Start node
   - Verify specified image is used

4. **Test Error Handling:**
   - Use invalid server URL in configuration
   - Attempt to start node
   - Verify fallback to `latest` with warning message

### API Testing

```bash
# Test successful version detection
curl "http://localhost:5000/api/server/version?server_url=https://portal.vantage6.ai&api_path=/api"

# Test with invalid URL
curl "http://localhost:5000/api/server/version?server_url=https://invalid.example.com&api_path=/api"

# Test without server_url parameter
curl "http://localhost:5000/api/server/version"
```

## Conclusion

The automatic version detection feature significantly improves the user experience by:
- Eliminating manual version configuration
- Reducing compatibility issues
- Maintaining flexibility for advanced users
- Providing clear visual feedback

Users can now start nodes with confidence that the correct version will be used automatically.
