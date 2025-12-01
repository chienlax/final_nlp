<#
.SYNOPSIS
    Vietnamese-English Code-Switching Speech Translation Project Setup Script
    
.DESCRIPTION
    This script sets up the entire project environment for a server-client architecture:
    - Server (your main desktop): Runs PostgreSQL, Label Studio, Audio Server via Docker
    - Clients (team laptops): Access Label Studio via browser to annotate
    
    Features:
    - Checks prerequisites (Docker Desktop)
    - Configures Windows Firewall for team access
    - Creates .env file with your API keys
    - Starts all Docker services
    - Creates Label Studio admin and team accounts
    - Generates TEAM_ACCESS.txt with connection info for team members
    
.NOTES
    Run this script as Administrator for firewall configuration.
    
.EXAMPLE
    # Run with default settings
    .\setup.ps1
    
    # Skip firewall configuration (if already done)
    .\setup.ps1 -SkipFirewall
    
    # Recreate team accounts
    .\setup.ps1 -RecreateUsers
#>

param(
    [switch]$SkipFirewall,
    [switch]$RecreateUsers,
    [switch]$Help
)

# =============================================================================
# CONFIGURATION
# =============================================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Service ports
$POSTGRES_PORT = 5433
$LABEL_STUDIO_PORT = 8085
$AUDIO_SERVER_PORT = 8081

# Colors for output
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Write-Step { param($step, $msg) Write-Host "`n=== Step $step : $msg ===" -ForegroundColor Magenta }

# =============================================================================
# HELP
# =============================================================================

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
    exit 0
}

# =============================================================================
# BANNER
# =============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════════════════════════╗
║     Vietnamese-English Code-Switching Speech Translation Project Setup        ║
║                                                                               ║
║     Server-Client Architecture for Team Annotation                            ║
╚═══════════════════════════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

# =============================================================================
# STEP 1: Check Prerequisites
# =============================================================================

Write-Step 1 "Checking Prerequisites"

# Check if running as Administrator (needed for firewall)
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $SkipFirewall) {
    Write-Warn "Not running as Administrator. Firewall rules cannot be configured."
    Write-Warn "Either run as Administrator, or use -SkipFirewall flag."
    $response = Read-Host "Continue without firewall configuration? (y/N)"
    if ($response -ne 'y' -and $response -ne 'Y') {
        Write-Err "Setup cancelled. Run as Administrator or use -SkipFirewall."
        exit 1
    }
    $SkipFirewall = $true
}

# Check Docker Desktop
Write-Info "Checking Docker Desktop..."
try {
    $dockerVersion = docker --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not found" }
    Write-Success "Docker found: $dockerVersion"
} catch {
    Write-Err "Docker Desktop is not installed or not in PATH."
    Write-Host ""
    Write-Host "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
    Write-Host "After installation, restart your computer and run this script again."
    exit 1
}

# Check Docker is running
Write-Info "Checking Docker daemon..."
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker not running" }
    Write-Success "Docker daemon is running"
} catch {
    Write-Err "Docker Desktop is not running."
    Write-Host ""
    Write-Host "Please start Docker Desktop and wait for it to be ready."
    Write-Host "Look for the whale icon in your system tray."
    exit 1
}

# Check docker-compose
Write-Info "Checking Docker Compose..."
try {
    $composeVersion = docker compose version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Compose not found" }
    Write-Success "Docker Compose found: $composeVersion"
} catch {
    Write-Err "Docker Compose not found. Please update Docker Desktop."
    exit 1
}

# =============================================================================
# STEP 2: Configure Environment (.env file)
# =============================================================================

Write-Step 2 "Configuring Environment"

$envFile = Join-Path $ProjectRoot ".env"
$envExampleFile = Join-Path $ProjectRoot ".env.example"

if (Test-Path $envFile) {
    Write-Info ".env file already exists."
    $response = Read-Host "Overwrite existing .env file? (y/N)"
    if ($response -ne 'y' -and $response -ne 'Y') {
        Write-Info "Keeping existing .env file."
    } else {
        Remove-Item $envFile
    }
}

if (-not (Test-Path $envFile)) {
    Write-Info "Creating .env file..."
    
    # Prompt for Gemini API Key
    Write-Host ""
    Write-Host "You need a Gemini API key for audio transcription/translation." -ForegroundColor Yellow
    Write-Host "Get one free at: https://aistudio.google.com/app/apikey" -ForegroundColor Yellow
    Write-Host ""
    
    $geminiKey1 = Read-Host "Enter your Gemini API Key (or press Enter to skip)"
    $geminiKey2 = Read-Host "Enter backup Gemini API Key (optional, press Enter to skip)"
    
    # Generate a random Label Studio API key (will be set after LS starts)
    $lsApiKey = "WILL_BE_SET_AFTER_SETUP"
    
    # Create .env content
    $envContent = @"
# =============================================================================
# Vietnamese-English CS Speech Translation Project Configuration
# Generated by setup.ps1 on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# =============================================================================

# -----------------------------------------------------------------------------
# Database Configuration
# -----------------------------------------------------------------------------
POSTGRES_USER=admin
POSTGRES_PASSWORD=secret_password
POSTGRES_DB=data_factory

# For local scripts (outside Docker) - use port 5433
DATABASE_URL=postgresql://admin:secret_password@localhost:5433/data_factory

# -----------------------------------------------------------------------------
# Label Studio Configuration
# -----------------------------------------------------------------------------
LABEL_STUDIO_URL=http://localhost:$LABEL_STUDIO_PORT
LABEL_STUDIO_API_KEY=$lsApiKey

# Project ID for unified review (transcription + translation)
LS_PROJECT_UNIFIED_REVIEW=1

# -----------------------------------------------------------------------------
# Audio Server Configuration
# -----------------------------------------------------------------------------
AUDIO_SERVER_URL=http://localhost:$AUDIO_SERVER_PORT

# -----------------------------------------------------------------------------
# Gemini API Keys (for transcription/translation)
# -----------------------------------------------------------------------------
GEMINI_API_KEY_1=$geminiKey1
GEMINI_API_KEY_2=$geminiKey2

# -----------------------------------------------------------------------------
# Sync Service Configuration
# -----------------------------------------------------------------------------
SYNC_INTERVAL_MINUTES=5
"@

    Set-Content -Path $envFile -Value $envContent -Encoding UTF8
    Write-Success ".env file created"
}

# =============================================================================
# STEP 3: Configure Windows Firewall
# =============================================================================

Write-Step 3 "Configuring Windows Firewall"

if ($SkipFirewall) {
    Write-Info "Skipping firewall configuration (use -SkipFirewall was specified or not running as Admin)"
} else {
    Write-Info "Adding firewall rules for team access..."
    
    # Define firewall rules
    $firewallRules = @(
        @{
            Name = "Label Studio (Team Access)"
            Port = $LABEL_STUDIO_PORT
            Description = "Allow team members to access Label Studio for annotation"
        },
        @{
            Name = "Audio Server (Team Access)"
            Port = $AUDIO_SERVER_PORT
            Description = "Allow team members to stream audio files"
        }
    )
    
    foreach ($rule in $firewallRules) {
        $existingRule = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
        
        if ($existingRule) {
            Write-Info "Firewall rule '$($rule.Name)' already exists."
        } else {
            try {
                New-NetFirewallRule `
                    -DisplayName $rule.Name `
                    -Description $rule.Description `
                    -Direction Inbound `
                    -Protocol TCP `
                    -LocalPort $rule.Port `
                    -Action Allow `
                    -Profile Private,Domain `
                    | Out-Null
                Write-Success "Created firewall rule: $($rule.Name) (Port $($rule.Port))"
            } catch {
                Write-Warn "Failed to create firewall rule: $($rule.Name). Error: $_"
            }
        }
    }
    
    Write-Info "Firewall rules configured for Private and Domain networks."
    Write-Warn "For Public networks (coffee shops, etc.), you may need to manually enable these rules."
}

# =============================================================================
# STEP 4: Start Docker Services
# =============================================================================

Write-Step 4 "Starting Docker Services"

Set-Location $ProjectRoot

Write-Info "Pulling latest Docker images..."
docker compose pull 2>&1 | Out-Null

Write-Info "Starting services (this may take a few minutes on first run)..."
docker compose up -d

Write-Info "Waiting for services to be healthy..."
$maxWait = 120  # seconds
$waited = 0
$interval = 5

do {
    Start-Sleep -Seconds $interval
    $waited += $interval
    
    # Check PostgreSQL
    $pgHealth = docker inspect --format='{{.State.Health.Status}}' factory_ledger 2>$null
    # Check Audio Server
    $audioHealth = docker inspect --format='{{.State.Health.Status}}' audio_server 2>$null
    # Check Label Studio (no health check, just running)
    $lsRunning = docker inspect --format='{{.State.Running}}' labelstudio 2>$null
    
    Write-Host "  PostgreSQL: $pgHealth | Audio Server: $audioHealth | Label Studio: $lsRunning" -ForegroundColor Gray
    
    if ($pgHealth -eq "healthy" -and $audioHealth -eq "healthy" -and $lsRunning -eq "true") {
        break
    }
    
    if ($waited -ge $maxWait) {
        Write-Warn "Timeout waiting for services. They may still be starting..."
        break
    }
} while ($true)

Write-Success "Docker services started"

# Give Label Studio a bit more time to fully initialize
Write-Info "Waiting for Label Studio to fully initialize (30 seconds)..."
Start-Sleep -Seconds 30

# =============================================================================
# STEP 5: Create Label Studio Users
# =============================================================================

Write-Step 5 "Setting up Label Studio Users"

# Enable legacy API tokens in Label Studio
Write-Info "Enabling legacy API tokens in Label Studio..."
try {
    docker exec -i factory_ledger psql -U admin -d label_studio -c "UPDATE core_organization SET legacy_enabled = true WHERE id = 1;" 2>&1 | Out-Null
    Write-Success "Legacy API tokens enabled"
} catch {
    Write-Warn "Could not enable legacy tokens (Label Studio may not be fully initialized)"
}

# Define team members (modify this list for your team)
$teamMembers = @(
    @{ Username = "admin"; Email = "admin@nlp-project.local"; Password = "admin123"; IsAdmin = $true },
    @{ Username = "annotator1"; Email = "annotator1@nlp-project.local"; Password = "annotate123"; IsAdmin = $false },
    @{ Username = "annotator2"; Email = "annotator2@nlp-project.local"; Password = "annotate123"; IsAdmin = $false }
)

Write-Host ""
Write-Host "Default team accounts to create:" -ForegroundColor Yellow
foreach ($member in $teamMembers) {
    $role = if ($member.IsAdmin) { "Admin" } else { "Annotator" }
    Write-Host "  - $($member.Username) ($role)" -ForegroundColor Gray
}
Write-Host ""

$createUsers = Read-Host "Create these accounts? You can add more later. (Y/n)"
if ($createUsers -eq 'n' -or $createUsers -eq 'N') {
    Write-Info "Skipping user creation. Users can sign up manually at Label Studio."
} else {
    Write-Info "Creating Label Studio user accounts..."
    
    # Create users via Django management command inside the container
    foreach ($member in $teamMembers) {
        $username = $member.Username
        $email = $member.Email
        $password = $member.Password
        
        # Check if user exists
        $checkCmd = "from django.contrib.auth import get_user_model; User = get_user_model(); print('exists' if User.objects.filter(email='$email').exists() else 'not_exists')"
        $userExists = docker exec labelstudio python -c "$checkCmd" 2>$null
        
        if ($userExists -eq "exists" -and -not $RecreateUsers) {
            Write-Info "User '$username' already exists, skipping."
            continue
        }
        
        # Create user
        $createCmd = @"
from django.contrib.auth import get_user_model
User = get_user_model()
try:
    user, created = User.objects.get_or_create(email='$email', defaults={'username': '$username'})
    user.set_password('$password')
    user.is_staff = $($member.IsAdmin.ToString().ToLower())
    user.is_superuser = $($member.IsAdmin.ToString().ToLower())
    user.save()
    print('created' if created else 'updated')
except Exception as e:
    print(f'error: {e}')
"@
        
        try {
            $result = docker exec labelstudio python -c "$createCmd" 2>$null
            if ($result -eq "created") {
                Write-Success "Created user: $username"
            } elseif ($result -eq "updated") {
                Write-Success "Updated user: $username"
            } else {
                Write-Warn "User creation result for $username : $result"
            }
        } catch {
            Write-Warn "Failed to create user $username : $_"
        }
    }
}

# =============================================================================
# STEP 6: Get Admin API Token
# =============================================================================

Write-Step 6 "Retrieving Admin API Token"

Write-Info "Fetching API token for admin user..."

$getTokenCmd = @"
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
User = get_user_model()
try:
    user = User.objects.filter(is_superuser=True).first()
    if user:
        token, _ = Token.objects.get_or_create(user=user)
        print(token.key)
    else:
        print('NO_ADMIN')
except Exception as e:
    print(f'ERROR:{e}')
"@

try {
    $apiToken = docker exec labelstudio python -c "$getTokenCmd" 2>$null
    
    if ($apiToken -and $apiToken -ne "NO_ADMIN" -and -not $apiToken.StartsWith("ERROR:")) {
        Write-Success "Retrieved API token: $($apiToken.Substring(0,8))..."
        
        # Update .env file with the token
        $envContent = Get-Content $envFile -Raw
        $envContent = $envContent -replace "LABEL_STUDIO_API_KEY=.*", "LABEL_STUDIO_API_KEY=$apiToken"
        Set-Content -Path $envFile -Value $envContent -Encoding UTF8
        Write-Success "Updated .env with API token"
    } else {
        Write-Warn "Could not retrieve API token. You may need to get it manually from Label Studio."
    }
} catch {
    Write-Warn "Failed to retrieve API token: $_"
}

# =============================================================================
# STEP 7: Get Server IP and Generate Team Access Info
# =============================================================================

Write-Step 7 "Generating Team Access Information"

# Get all network adapters and their IPs
Write-Info "Detecting server IP addresses..."

# Check for Tailscale IP first (preferred for remote access)
$tailscaleIP = $null
try {
    $tailscaleIP = (tailscale ip -4 2>$null)
    if ($tailscaleIP) {
        Write-Success "Tailscale detected: $tailscaleIP"
    }
} catch {
    Write-Info "Tailscale not installed or not running"
}

# Also check from .env file if Tailscale IP is configured
$envContent = Get-Content $envFile -Raw
if ($envContent -match "TAILSCALE_IP=([0-9.]+)") {
    $configuredTailscaleIP = $Matches[1].Trim()
    if (-not $tailscaleIP) {
        $tailscaleIP = $configuredTailscaleIP
        Write-Info "Using Tailscale IP from .env: $tailscaleIP"
    }
}

$networkInfo = Get-NetIPAddress -AddressFamily IPv4 | 
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object IPAddress, InterfaceAlias

$lanIP = $null
foreach ($net in $networkInfo) {
    # Prefer Ethernet or Wi-Fi adapters (skip Tailscale interface for LAN IP)
    if ($net.InterfaceAlias -match "Ethernet|Wi-Fi|WLAN|LAN" -and $net.InterfaceAlias -notmatch "Tailscale") {
        $lanIP = $net.IPAddress
        break
    }
}

# Fallback to first non-localhost, non-Tailscale IP
if (-not $lanIP -and $networkInfo.Count -gt 0) {
    $lanIP = ($networkInfo | Where-Object { $_.InterfaceAlias -notmatch "Tailscale" } | Select-Object -First 1).IPAddress
}

if (-not $lanIP) {
    Write-Warn "Could not detect LAN IP. Using localhost."
    $lanIP = "localhost"
}

Write-Success "LAN IP: $lanIP"

# Determine primary IP for team access (prefer Tailscale for remote teams)
$primaryIP = if ($tailscaleIP) { $tailscaleIP } else { $lanIP }

# Generate TEAM_ACCESS.txt
$teamAccessFile = Join-Path $ProjectRoot "TEAM_ACCESS.txt"

# Build access content based on whether Tailscale is available
if ($tailscaleIP) {
    $teamAccessContent = @"
================================================================================
   Vietnamese-English Code-Switching Speech Translation Project
   Team Access Information (via Tailscale VPN)
================================================================================

Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Server: $env:COMPUTERNAME

--------------------------------------------------------------------------------
TAILSCALE REMOTE ACCESS (for team on different networks)
--------------------------------------------------------------------------------

IMPORTANT: You must have Tailscale installed and connected to access this server!

1. Install Tailscale: https://tailscale.com/download
2. Sign in with your team invite link (ask the admin)
3. Once connected, access Label Studio at:

   Label Studio:  http://${tailscaleIP}:$LABEL_STUDIO_PORT
   Audio Server:  http://${tailscaleIP}:$AUDIO_SERVER_PORT

--------------------------------------------------------------------------------
LOCAL NETWORK ACCESS (same WiFi/LAN only)
--------------------------------------------------------------------------------

URL: http://${lanIP}:$LABEL_STUDIO_PORT

--------------------------------------------------------------------------------
DEFAULT ACCOUNTS
--------------------------------------------------------------------------------

  Admin:      admin@nlp-project.local / admin123
  Annotator:  annotator1@nlp-project.local / annotate123
  Annotator:  annotator2@nlp-project.local / annotate123

Or sign up with your own email at the URL above.

--------------------------------------------------------------------------------
QUICK START FOR TEAM MEMBERS
--------------------------------------------------------------------------------

1. Install Tailscale and connect to the team network
2. Open Label Studio URL in your browser (Chrome recommended)
3. Log in with your assigned account or create a new one
4. Go to "Projects" and select the annotation project
5. Click on a task to start annotating
6. Your work is auto-saved to the server

--------------------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------------------

Can't connect via Tailscale?
  - Ensure Tailscale is running (check system tray icon)
  - Verify you're connected: run 'tailscale status' in terminal
  - Check if server is online: ping $tailscaleIP
  - Make sure you've accepted the invite to the Tailscale network

Audio not playing?
  - Make sure your browser allows autoplay
  - Try refreshing the page
  - Check if audio server is accessible: http://${tailscaleIP}:$AUDIO_SERVER_PORT

--------------------------------------------------------------------------------
FOR SERVER ADMIN ONLY
--------------------------------------------------------------------------------

Tailscale IP: $tailscaleIP
LAN IP:       $lanIP

Server Local Access:
  Label Studio: http://localhost:$LABEL_STUDIO_PORT
  Audio Server: http://localhost:$AUDIO_SERVER_PORT
  PostgreSQL:   localhost:$POSTGRES_PORT

Docker Commands:
  View logs:    docker compose logs -f
  Restart:      docker compose restart
  Stop:         docker compose down
  Start:        docker compose up -d

Tailscale Admin:
  Invite users: https://login.tailscale.com/admin/users
  View devices: tailscale status

API Token (for scripts): Check .env file

================================================================================
"@
} else {
    $teamAccessContent = @"
================================================================================
   Vietnamese-English Code-Switching Speech Translation Project
   Team Access Information
================================================================================

Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Server: $env:COMPUTERNAME

--------------------------------------------------------------------------------
LABEL STUDIO ACCESS (for annotation)
--------------------------------------------------------------------------------

URL: http://${lanIP}:$LABEL_STUDIO_PORT

NOTE: This URL only works on the same local network (WiFi/LAN).
For remote access, install Tailscale and run setup again.

Default Accounts:
  Admin:      admin@nlp-project.local / admin123
  Annotator:  annotator1@nlp-project.local / annotate123
  Annotator:  annotator2@nlp-project.local / annotate123

Or sign up with your own email at the URL above.

--------------------------------------------------------------------------------
QUICK START FOR TEAM MEMBERS
--------------------------------------------------------------------------------

1. Open the URL above in your browser (Chrome recommended)
2. Log in with your assigned account or create a new one
3. Go to "Projects" and select the annotation project
4. Click on a task to start annotating
5. Your work is auto-saved to the server

--------------------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------------------

Can't connect to Label Studio?
  - Make sure you're on the same network as the server ($env:COMPUTERNAME)
  - Ask the server admin if the firewall is configured
  - Try: ping $lanIP

Audio not playing?
  - Make sure your browser allows autoplay
  - Try refreshing the page
  - Check if audio server is accessible: http://${lanIP}:$AUDIO_SERVER_PORT

Need help?
  - Contact the project admin
  - Check the docs/ folder for detailed documentation

--------------------------------------------------------------------------------
FOR SERVER ADMIN ONLY
--------------------------------------------------------------------------------

Server Local Access:
  Label Studio: http://localhost:$LABEL_STUDIO_PORT
  Audio Server: http://localhost:$AUDIO_SERVER_PORT
  PostgreSQL:   localhost:$POSTGRES_PORT

Docker Commands:
  View logs:    docker compose logs -f
  Restart:      docker compose restart
  Stop:         docker compose down
  Start:        docker compose up -d

API Token (for scripts): Check .env file

================================================================================
"@
}

Set-Content -Path $teamAccessFile -Value $teamAccessContent -Encoding UTF8
Write-Success "Created TEAM_ACCESS.txt"

# =============================================================================
# STEP 8: Create Default Project
# =============================================================================

Write-Step 8 "Setting Up Default Project"

# Check if project exists
Write-Info "Checking for existing projects..."

# We'll use the API to create a project
$lsUrl = "http://localhost:$LABEL_STUDIO_PORT"

# Read the current API token from .env
$envContent = Get-Content $envFile -Raw
if ($envContent -match "LABEL_STUDIO_API_KEY=(.+)") {
    $apiToken = $Matches[1].Trim()
}

if ($apiToken -and $apiToken -ne "WILL_BE_SET_AFTER_SETUP") {
    Write-Info "Creating default annotation project..."
    
    # Read the unified review template
    $templateFile = Join-Path $ProjectRoot "label_studio_templates\unified_review.xml"
    if (Test-Path $templateFile) {
        $labelConfig = Get-Content $templateFile -Raw
        $labelConfig = $labelConfig -replace '"', '\"' -replace "`r`n", "\n" -replace "`n", "\n"
    } else {
        Write-Warn "Template file not found: $templateFile"
        $labelConfig = "<View><Text name=`"text`" value=`"`$text`"/></View>"
    }
    
    $projectBody = @{
        title = "CS Speech Translation Review"
        description = "Unified review for Vietnamese-English code-switched speech transcription and translation"
        label_config = $labelConfig
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod -Uri "$lsUrl/api/projects/" `
            -Method Get `
            -Headers @{ "Authorization" = "Token $apiToken" } `
            -ContentType "application/json" 2>$null
        
        if ($response.results.Count -eq 0) {
            # Create project
            $createResponse = Invoke-RestMethod -Uri "$lsUrl/api/projects/" `
                -Method Post `
                -Headers @{ "Authorization" = "Token $apiToken" } `
                -ContentType "application/json" `
                -Body $projectBody 2>$null
            
            Write-Success "Created project: $($createResponse.title) (ID: $($createResponse.id))"
        } else {
            Write-Info "Project(s) already exist. Skipping creation."
        }
    } catch {
        Write-Warn "Could not create project via API. You can create it manually in Label Studio."
    }
} else {
    Write-Warn "No API token available. Create the project manually in Label Studio."
}

# =============================================================================
# DONE!
# =============================================================================

Write-Host ""
Write-Host "=================================================================================" -ForegroundColor Green
Write-Host "                         SETUP COMPLETE!" -ForegroundColor Green
Write-Host "=================================================================================" -ForegroundColor Green
Write-Host ""

Write-Host "Server is running at:" -ForegroundColor Cyan
Write-Host "  Label Studio:  http://localhost:$LABEL_STUDIO_PORT" -ForegroundColor White
Write-Host "  Audio Server:  http://localhost:$AUDIO_SERVER_PORT" -ForegroundColor White
Write-Host ""

Write-Host "Team members can access Label Studio at:" -ForegroundColor Cyan
Write-Host "  http://${primaryIP}:$LABEL_STUDIO_PORT" -ForegroundColor Yellow
Write-Host ""

Write-Host "Share the TEAM_ACCESS.txt file with your team for connection instructions." -ForegroundColor Cyan
Write-Host ""

Write-Host "Default admin login:" -ForegroundColor Cyan
Write-Host "  Email:    admin@nlp-project.local" -ForegroundColor White
Write-Host "  Password: admin123" -ForegroundColor White
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Open Label Studio in your browser" -ForegroundColor White
Write-Host "  2. Log in with the admin account" -ForegroundColor White
Write-Host "  3. Import data using: docker compose run --rm ingestion python src/ingest_youtube.py" -ForegroundColor White
Write-Host "  4. Share TEAM_ACCESS.txt with your team" -ForegroundColor White
Write-Host ""

# Open Label Studio in browser
$openBrowser = Read-Host "Open Label Studio in browser now? (Y/n)"
if ($openBrowser -ne 'n' -and $openBrowser -ne 'N') {
    Start-Process "http://localhost:$LABEL_STUDIO_PORT"
}
