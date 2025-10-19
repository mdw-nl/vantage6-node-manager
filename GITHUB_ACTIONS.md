# GitHub Actions Workflows

This repository includes automated CI/CD workflows for building, testing, and publishing Docker images.

## 📋 Available Workflows

### 1. Docker Build and Push (`docker-build.yml`)

**Purpose**: Automatically builds and pushes Docker images to GitHub Container Registry.

**Triggers**:
- Push to `main` or `develop` branches
- Pull requests to `main`
- Git tags matching `v*.*.*` (e.g., `v1.0.0`)
- Manual workflow dispatch

**What it does**:
- ✅ Builds Docker image for multiple platforms (amd64, arm64)
- ✅ Pushes to GitHub Container Registry (ghcr.io)
- ✅ Creates tags based on branches, PRs, and semantic versions
- ✅ Uses build cache for faster builds
- ✅ Generates attestation for supply chain security

**Image Tags Created**:
- `main` → `ghcr.io/mdw-nl/vantage6-node-manager:main`, `latest`
- `develop` → `ghcr.io/mdw-nl/vantage6-node-manager:develop`
- `v1.2.3` → `ghcr.io/mdw-nl/vantage6-node-manager:1.2.3`, `1.2`, `1`
- PRs → `ghcr.io/mdw-nl/vantage6-node-manager:pr-123`

### 2. Docker Image CI Tests (`docker-test.yml`)

**Purpose**: Tests Docker image build and functionality.

**Triggers**:
- Pull requests to `main` or `develop`
- Push to `main` or `develop`

**What it does**:
- ✅ Builds Docker image
- ✅ Tests container startup
- ✅ Tests health endpoint (HTTP 200)
- ✅ Verifies Python dependencies
- ✅ Lints Dockerfile with Hadolint
- ✅ Scans for security vulnerabilities with Trivy

### 3. Multi-Registry Release (`release.yml`)

**Purpose**: Publishes Docker images to multiple registries on release.

**Triggers**:
- GitHub release published
- Manual workflow dispatch

**What it does**:
- ✅ Builds for multiple platforms (amd64, arm64)
- ✅ Pushes to GitHub Container Registry
- ✅ Optionally pushes to Docker Hub (if configured)
- ✅ Creates version and latest tags
- ✅ Generates deployment summary

## 🚀 Usage

### Pulling Images

#### From GitHub Container Registry (Default)

```bash
# Pull latest version
docker pull ghcr.io/mdw-nl/vantage6-node-manager:latest

# Pull specific version
docker pull ghcr.io/mdw-nl/vantage6-node-manager:1.0.0

# Pull from specific branch
docker pull ghcr.io/mdw-nl/vantage6-node-manager:main
```

#### Authentication for Private Images

If the repository is private:

```bash
# Create a Personal Access Token (PAT) with read:packages scope
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Then pull the image
docker pull ghcr.io/mdw-nl/vantage6-node-manager:latest
```

### Using in docker-compose.yml

Update your `docker-compose.yml` to use the published image:

```yaml
services:
  vantage6-node-manager:
    image: ghcr.io/mdw-nl/vantage6-node-manager:latest
    # or specific version:
    # image: ghcr.io/mdw-nl/vantage6-node-manager:1.0.0
    ports:
      - "5000:5000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ${HOME}/.config/vantage6:/root/.config/vantage6
    environment:
      - SECRET_KEY=${SECRET_KEY}
    restart: unless-stopped
```

## 🔐 Repository Secrets

### Required Secrets

None required for GitHub Container Registry (uses `GITHUB_TOKEN` automatically).

### Optional Secrets (for Docker Hub)

To enable Docker Hub publishing, add these secrets to your repository:

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Add the following secrets:

| Secret Name | Description |
|-------------|-------------|
| `DOCKERHUB_USERNAME` | Your Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |

**Creating Docker Hub Access Token**:
1. Log in to Docker Hub
2. Go to Account Settings → Security
3. Click "New Access Token"
4. Give it a description and select appropriate permissions
5. Copy the token and add it to GitHub secrets

## 📦 Image Platforms

All images are built for multiple architectures:
- `linux/amd64` (Intel/AMD processors)
- `linux/arm64` (ARM processors, e.g., Apple Silicon, Raspberry Pi)

Docker will automatically pull the correct image for your platform.

## 🏷️ Tagging Strategy

### Semantic Versioning (for releases)

When you create a release with tag `v1.2.3`, the following tags are created:
- `1.2.3` - Exact version
- `1.2` - Minor version
- `1` - Major version
- `latest` - Always points to the latest release

### Branch-based Tags

- `main` - Latest from main branch + `latest` tag
- `develop` - Latest from develop branch
- `pr-123` - Pull request #123

### SHA-based Tags

Each commit gets a tag with the format: `{branch}-{short-sha}`
Example: `main-a1b2c3d`

## 🔧 Workflow Configuration

### Enabling/Disabling Workflows

Edit the workflow files in `.github/workflows/` to customize:

**Disable a workflow**:
```yaml
on:
  # Comment out or remove triggers
  # push:
  #   branches: [main]
```

**Change trigger branches**:
```yaml
on:
  push:
    branches:
      - main
      - staging  # Add more branches
```

### Customizing Build Platforms

To build for different platforms, edit the `platforms` field:

```yaml
platforms: linux/amd64,linux/arm64,linux/arm/v7
```

## 🧪 Testing Locally

### Test Docker Build

```bash
# Build image
docker build -t vantage6-node-manager:test .

# Test container
docker run -d --name test \
  -p 5000:5000 \
  -e SECRET_KEY=test-key \
  vantage6-node-manager:test

# Check logs
docker logs test

# Test endpoint
curl http://localhost:5000/

# Cleanup
docker stop test && docker rm test
```

### Test Multi-platform Build

Requires Docker Buildx:

```bash
# Create builder
docker buildx create --name multiplatform --use

# Build for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t vantage6-node-manager:multiplatform \
  --push \
  .
```

## 📊 Workflow Status Badges

Add status badges to your README:

```markdown
[![Docker Build](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-build.yml/badge.svg)](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-build.yml)

[![Docker Tests](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-test.yml/badge.svg)](https://github.com/mdw-nl/vantage6-node-manager/actions/workflows/docker-test.yml)
```

## 🔍 Monitoring Workflows

### View Workflow Runs

1. Go to **Actions** tab in GitHub
2. Select a workflow from the left sidebar
3. View run history and logs

### Debug Failed Runs

1. Click on a failed run
2. Expand the failed step
3. View logs for error details
4. Re-run failed jobs if needed

## 🚨 Security Features

### Trivy Vulnerability Scanning

- Automatically scans for known vulnerabilities
- Results uploaded to GitHub Security tab
- Fails on critical vulnerabilities

### Hadolint Dockerfile Linting

- Checks Dockerfile best practices
- Ensures security and efficiency
- Warns on common mistakes

### Supply Chain Security

- Build attestations for provenance tracking
- Signed with GitHub's signing certificate
- Verifiable with cosign

## 📝 Best Practices

1. **Always tag releases** with semantic versions (`v1.0.0`)
2. **Test in develop** before merging to main
3. **Review security scan results** before deploying
4. **Use specific version tags** in production (not `latest`)
5. **Keep secrets secure** - never commit them
6. **Monitor workflow runs** for failures
7. **Update actions** regularly for security patches

## 🔄 Updating Workflows

To update GitHub Actions versions:

```bash
# Check for outdated actions
gh actions list

# Update to latest versions in workflow files
# Example: actions/checkout@v3 → actions/checkout@v4
```

## 🆘 Troubleshooting

### Build Fails on Push

**Issue**: Workflow fails with permission error

**Solution**: 
1. Go to **Settings** → **Actions** → **General**
2. Under "Workflow permissions", select:
   - ✅ Read and write permissions
   - ✅ Allow GitHub Actions to create and approve pull requests

### Image Push Fails

**Issue**: Cannot push to ghcr.io

**Solution**:
1. Check repository visibility (public/private)
2. Verify package permissions in Settings → Packages
3. Ensure workflow has `packages: write` permission

### Multi-platform Build Slow

**Issue**: ARM builds take too long

**Solution**:
- Use GitHub Actions cache (already configured)
- Consider disabling ARM builds for PRs
- Use self-hosted ARM runners for faster builds

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Docker Buildx](https://docs.docker.com/buildx/working-with-buildx/)
- [Trivy Security Scanner](https://github.com/aquasecurity/trivy)
