"""
Manual Google Drive OAuth authentication for DVC.
This triggers the browser-based OAuth flow to get fresh credentials.
Saves credentials to the pydrive2fs cache location that DVC uses.
"""
import json
from pathlib import Path
from pydrive2.auth import GoogleAuth

# Configuration
PROJECT_ROOT = Path(__file__).parent
SECRETS_DIR = PROJECT_ROOT / '.secrets'
CLIENT_SECRET = SECRETS_DIR / 'client_secret_952625721816-dc9kkk15i2leugvjl8f885rqkut975bo.apps.googleusercontent.com.json'

# DVC/pydrive2fs expects credentials here
CACHE_DIR = Path.home() / '.cache' / 'pydrive2fs'
CREDENTIALS_FILE = CACHE_DIR / 'credentials.json'

print("=" * 70)
print("Google Drive OAuth Authentication for DVC")
print("=" * 70)
print()
print(f"Using client secret: {CLIENT_SECRET.name}")
print(f"Saving credentials to: {CREDENTIALS_FILE}")
print()
print("A browser window will open. Please:")
print("1. Sign in with your Google account")
print("2. Grant access to Google Drive")
print("3. Return here after authorization")
print()
print("=" * 70)
print()

# Ensure cache directory exists
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Configure GoogleAuth
gauth = GoogleAuth()
gauth.settings['client_config_file'] = str(CLIENT_SECRET)
gauth.settings['get_refresh_token'] = True

# Trigger browser-based authentication
gauth.LocalWebserverAuth()

# Manually save credentials to the DVC cache location
credentials_data = {
    'access_token': gauth.credentials.access_token,
    'client_id': gauth.credentials.client_id,
    'client_secret': gauth.credentials.client_secret,
    'refresh_token': gauth.credentials.refresh_token,
    'token_expiry': gauth.credentials.token_expiry.isoformat() if gauth.credentials.token_expiry else None,
    'token_uri': gauth.credentials.token_uri,
    'user_agent': gauth.credentials.user_agent,
    'revoke_uri': gauth.credentials.revoke_uri,
    'id_token': gauth.credentials.id_token,
    'token_response': gauth.credentials.token_response,
    'scopes': list(gauth.credentials.scopes) if gauth.credentials.scopes else [],
    'token_info_uri': gauth.credentials.token_info_uri,
    'id_token_jwt': gauth.credentials.id_token_jwt
}

with open(CREDENTIALS_FILE, 'w') as f:
    json.dump(credentials_data, f, indent=2)

print()
print("✓ Authentication successful!")
print()
print(f"Credentials saved to: {CREDENTIALS_FILE}")
print()
print("You can now use DVC commands:")
print(r"  .\.venv\Scripts\python.exe -m dvc push")
print(r"  .\.venv\Scripts\python.exe -m dvc pull")
print()
