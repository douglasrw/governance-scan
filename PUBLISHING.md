# Publishing governance-scan to PyPI

## One-Time Setup (Manual Steps)

The GitHub Actions workflow `.github/workflows/publish.yml` is configured for OIDC trusted publishing. To activate it:

1. **Create a PyPI account** at https://pypi.org/account/register/ (if not already done)

2. **Create the project on PyPI** by doing the first manual upload:
   ```bash
   cd /data/projects/governance-scan
   python -m build
   twine upload dist/*
   # Enter PyPI username and password/token when prompted
   ```

3. **Configure trusted publishing** on PyPI (recommended, replaces API tokens):
   - Go to https://pypi.org/manage/project/governance-scan/settings/publishing/
   - Add a new publisher:
     - Owner: `douglasrw`
     - Repository: `governance-scan`
     - Workflow name: `publish.yml`
     - Environment name: `pypi`
   - This enables the GitHub Actions workflow to publish without any stored secrets

4. **Alternative: API token** (if trusted publishing is not preferred):
   - Generate a token at https://pypi.org/manage/account/token/
   - Add it as a GitHub secret named `PYPI_API_TOKEN` in the repo settings
   - Update `.github/workflows/publish.yml` to use the token instead of OIDC

## After Setup

Once configured, new releases will automatically publish to PyPI when you create a GitHub Release. The workflow triggers on the `release: published` event.

## Pre-built Artifacts

The package has been built and verified locally. Artifacts are in `dist/`:
- `governance_scan-1.0.0.tar.gz` (sdist)
- `governance_scan-1.0.0-py3-none-any.whl` (wheel)

# Publishing to GitHub Marketplace

## Steps (requires GitHub UI)

1. Go to https://github.com/douglasrw/governance-scan/releases/tag/v1.0.0
2. Click "Edit" on the release
3. Check the box "Publish this Action to the GitHub Marketplace"
4. Select the "Security" category (or "Code quality")
5. Save the release

The `action.yml` already has the required `branding` section (icon: shield, color: blue) for Marketplace listing.
