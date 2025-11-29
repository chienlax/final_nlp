"""
Google Drive OAuth Setup Script for DVC.

One-time script to authenticate with Google Drive for DVC remote storage.
This script reads the OAuth client secret from .secrets/ and initiates
the browser-based authentication flow.

Usage:
    python src/setup_gdrive_auth.py           # Run OAuth flow
    python src/setup_gdrive_auth.py --check   # Check if already authenticated
    python src/setup_gdrive_auth.py --help    # Show instructions

Prerequisites:
    1. Place client_secret_*.json in .secrets/ folder
    2. You must be added as a test user in Google Cloud Console
       (if app is in "Testing" status)

Note:
    The OAuth library uses port 8080 for the callback redirect.
    Label Studio has been moved to port 8085 to avoid conflict.
    No action needed - just run this script while Docker is running.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('setup_gdrive_auth')

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / '.secrets'
DVC_CONFIG_DIR = PROJECT_ROOT / '.dvc'
PYDRIVE_CACHE_DIR = Path.home() / '.cache' / 'pydrive2fs'


def find_client_secret() -> Optional[Path]:
    """
    Find the Google OAuth client secret file in .secrets/ directory.

    Returns:
        Path to the client secret file, or None if not found.
    """
    if not SECRETS_DIR.exists():
        return None

    for file in SECRETS_DIR.glob('client_secret_*.json'):
        return file

    return None


def extract_credentials(client_secret_path: Path) -> dict:
    """
    Extract client_id and client_secret from the JSON file.

    Args:
        client_secret_path: Path to the client_secret JSON file.

    Returns:
        Dictionary with 'client_id' and 'client_secret'.
    """
    with open(client_secret_path, 'r') as f:
        data = json.load(f)

    # Handle both 'installed' and 'web' application types
    if 'installed' in data:
        creds = data['installed']
    elif 'web' in data:
        creds = data['web']
    else:
        raise ValueError("Invalid client secret format")

    return {
        'client_id': creds['client_id'],
        'client_secret': creds['client_secret'],
    }


def check_existing_auth() -> bool:
    """
    Check if OAuth tokens already exist.

    Returns:
        True if authenticated, False otherwise.
    """
    # Check pydrive2fs cache
    token_file = PYDRIVE_CACHE_DIR / 'credentials.json'
    if token_file.exists():
        try:
            with open(token_file, 'r') as f:
                creds = json.load(f)
            if creds.get('access_token') or creds.get('refresh_token'):
                return True
        except (json.JSONDecodeError, KeyError):
            pass

    return False


def update_dvc_config(client_id: str, client_secret: str) -> None:
    """
    Update DVC config.local with Google Drive OAuth credentials.

    Uses config.local instead of config to avoid committing secrets to git.
    DVC automatically merges config.local with config.

    Args:
        client_id: Google OAuth client ID.
        client_secret: Google OAuth client secret.
    """
    config_local_path = DVC_CONFIG_DIR / 'config.local'

    # Create or overwrite config.local with gdrive settings
    content = f'''[remote "my_gdrive"]
    gdrive_use_service_account = false
    gdrive_client_id = {client_id}
    gdrive_client_secret = {client_secret}
'''
    config_local_path.write_text(content)
    logger.info(f"OAuth credentials saved to {config_local_path}")
    logger.info("  (config.local is not tracked by git - credentials stay local)")



def run_dvc_pull_test() -> bool:
    """
    Run a test DVC pull to trigger OAuth flow.

    Returns:
        True if successful, False otherwise.
    """
    import subprocess

    logger.info("Running 'dvc pull' to trigger OAuth authentication...")
    logger.info("A browser window should open for Google sign-in.")
    logger.info("")
    logger.info("=" * 60)
    logger.info("IMPORTANT: You must be added as a test user in Google Cloud Console!")
    logger.info("=" * 60)
    logger.info("")

    try:
        result = subprocess.run(
            ['dvc', 'pull', '--verbose'],
            cwd=str(PROJECT_ROOT),
            timeout=300,  # 5 minutes for auth flow
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("DVC pull timed out. Authentication may have failed.")
        return False
    except FileNotFoundError:
        logger.error("DVC command not found. Is DVC installed?")
        return False


def print_teammate_instructions(client_secret_path: Path) -> None:
    """
    Print setup instructions for teammates.

    Args:
        client_secret_path: Path to the client secret file.
    """
    instructions = f"""
================================================================================
                    GOOGLE DRIVE AUTHENTICATION SETUP
================================================================================

PREREQUISITES:
  1. You must be added as a "Test User" in Google Cloud Console
     (Contact the project owner if you're not added yet)
  2. You need the client_secret JSON file

SETUP STEPS:

  1. Copy the client secret file to your local .secrets/ folder:
     
     File: {client_secret_path.name}
     Location: <project_root>/.secrets/

  2. Run this setup script:
     
     python src/setup_gdrive_auth.py

  3. A browser window will open - sign in with your Google account
     (must be a test user!)

  4. After successful authentication, DVC will work automatically

VERIFICATION:

  Run this command to verify authentication:
  
    dvc pull --verbose

  You should see files being downloaded without authentication prompts.

TROUBLESHOOTING:

  - "Access blocked" error:
    → You're not added as a test user. Contact the project owner.

  - Browser doesn't open:
    → Copy the URL from terminal and open manually

  - Token expired:
    → Re-run this setup script

================================================================================
"""
    print(instructions)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Setup Google Drive OAuth authentication for DVC.'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check if already authenticated (no action)'
    )
    parser.add_argument(
        '--instructions',
        action='store_true',
        help='Print setup instructions for teammates'
    )
    parser.add_argument(
        '--skip-dvc-test',
        action='store_true',
        help='Skip the DVC pull test after configuration'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Find client secret
    client_secret_path = find_client_secret()

    if client_secret_path is None:
        logger.error("Client secret not found in .secrets/ directory!")
        logger.error("Please place your client_secret_*.json file there.")
        return 1

    logger.info(f"Found client secret: {client_secret_path.name}")

    # Print instructions if requested
    if args.instructions:
        print_teammate_instructions(client_secret_path)
        return 0

    # Check existing auth if requested
    if args.check:
        if check_existing_auth():
            logger.info("✓ Already authenticated with Google Drive")
            logger.info(f"  Token location: {PYDRIVE_CACHE_DIR}")
            return 0
        else:
            logger.warning("✗ Not authenticated yet")
            logger.info("  Run without --check to set up authentication")
            return 1

    # Extract credentials
    try:
        creds = extract_credentials(client_secret_path)
        logger.info(f"Client ID: {creds['client_id'][:20]}...")
    except Exception as e:
        logger.error(f"Failed to read client secret: {e}")
        return 1

    # Update DVC config
    logger.info("Updating DVC configuration...")
    try:
        update_dvc_config(creds['client_id'], creds['client_secret'])
    except Exception as e:
        logger.error(f"Failed to update DVC config: {e}")
        return 1

    # Create pydrive cache directory
    PYDRIVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Run DVC pull test to trigger auth flow
    if not args.skip_dvc_test:
        logger.info("")
        logger.info("=" * 60)
        logger.info("Starting OAuth authentication flow...")
        logger.info("=" * 60)
        logger.info("")

        success = run_dvc_pull_test()

        if success:
            logger.info("")
            logger.info("✓ Authentication successful!")
            logger.info(f"  Tokens saved to: {PYDRIVE_CACHE_DIR}")
            logger.info("")
            logger.info("You can now use DVC commands without re-authenticating.")
            return 0
        else:
            logger.error("")
            logger.error("✗ Authentication failed or incomplete")
            logger.error("  Please check the error messages above.")
            return 1
    else:
        logger.info("DVC config updated. Run 'dvc pull' manually to complete authentication.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
