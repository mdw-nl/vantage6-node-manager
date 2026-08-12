# Vantage6 Node Manager - Getting Started Guide

## Installation Steps

### Step 1: Prerequisites

Ensure you have the following installed:
- Docker (version 20.10 or higher)
- Docker Compose (version 2.0 or higher)

You can verify your installations:
```bash
docker --version
docker-compose --version
```

### Step 2: Clone and Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd vantage6-node-manager
```

2. Run the setup script:
```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Check for required dependencies
- Create a `.env` file with a secure random secret key
- Create the Vantage6 configuration directory

### Step 3: Start the Application

```bash
docker-compose up -d
```

Wait a few seconds for the application to start, then access it at:
```
http://localhost:5000
```

### Step 4: Create Your First Node

1. Click on **"Create New Node"** in the navigation
2. Fill in the form:
   - **Node Name**: e.g., `my-first-node`
   - **Server URL**: URL of your Vantage6 server
   - **API Key**: Your authentication key (get this from your server admin)
   - **Database URI**: Path to your data file, e.g., `/data/mydata.csv`
   - **Database Type**: Choose the type (CSV, Parquet, SQL, etc.)
3. Click **"Create Node Configuration"**

### Step 5: Start the Node

1. Go to the **Dashboard** or **Nodes** page
2. Find your newly created node
3. Click the **Start** button (▶️)
4. The node will start in a Docker container

### Step 6: Monitor Your Node

1. Click on the node name to view details
2. You'll see:
   - Configuration details
   - Container information
   - Real-time logs
3. Use the control buttons to:
   - Stop the node
   - Restart the node
   - View logs

## Common Workflows

### Managing Multiple Nodes

1. Create multiple node configurations using different names
2. Start/stop them independently from the dashboard
3. View all nodes at a glance on the nodes page

### Updating a Node Configuration

Currently, you need to:
1. Stop the node
2. Manually edit the YAML file in `~/.config/vantage6/node/`
3. Restart the node

*Note: A web-based configuration editor is planned for future releases*

### Viewing Logs

For running nodes:
1. Navigate to the node details page
2. Logs are displayed at the bottom and auto-refresh every 5 seconds
3. Use the "Refresh" button for manual updates

### Troubleshooting

If a node won't start:
1. Check the configuration file for syntax errors
2. Verify the API key is correct
3. Ensure data files exist and are accessible
4. Check Docker logs: `docker logs vantage6-<node-name>-user`

## Advanced Usage

### Custom Data Directory

To mount a custom data directory:

1. Edit `docker-compose.yml`:
```yaml
volumes:
  - /path/to/your/data:/data
```

2. Restart the application:
```bash
docker-compose down
docker-compose up -d
```

3. Reference data files as `/data/filename.csv` in node configurations

### Running Without Docker

If you prefer to run without Docker:

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python app.py
```

*Note: You'll still need Docker to run the node containers*

### Environment Configuration

Edit `.env` to customize:
- `SECRET_KEY`: Flask session secret (keep this secure!)
- `FLASK_ENV`: Set to `development` for debug mode

## Tips

- **Backup configurations**: Regularly backup `~/.config/vantage6/node/`
- **Security**: Change the SECRET_KEY in production
- **Monitoring**: Keep an eye on node logs for errors
- **Resources**: Ensure Docker has enough resources (memory, CPU)

## Next Steps

- Explore the API endpoints at `/api/nodes`
- Set up multiple nodes for different datasets
- Configure encryption in node settings (manual YAML edit)
- Join the Vantage6 community for support

## Need Help?

- Check the main README.md for detailed documentation
- Review the troubleshooting section
- Create an issue on GitHub
- Contact the Vantage6 community
