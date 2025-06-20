# Pipeline Setup Guide

Configure Mac-to-Mac photo transfer with automatic Apple Photos import.

## Overview

The pipeline system transfers edited photos from your scanning Mac (Mac A) to your Photos library Mac (Mac B):

```
Mac A (Scanning/Editing)          Mac B (Photos Library)
┌─────────────────────┐          ┌─────────────────────┐
│ 1. Edit metadata    │          │ 4. Automator watches │
│ 2. Save changes     │  ──SSH─> │ 5. Import to Photos  │
│ 3. Click Send       │  <─────  │ 6. Report success    │
└─────────────────────┘          └─────────────────────┘
```

## Prerequisites

- Part 1 (Metadata Editor) working on Mac A
- Two Macs on the same **wired ethernet network**
- Admin access on both Macs
- Apple Photos configured on Mac B

## Mac B Setup

### Step 1: Install Requirements

On Mac B, install Xcode Command Line Tools (required for Python):
```bash
xcode-select --install
```

### Step 2: Enable Remote Login

1. **System Preferences** → **Sharing**
2. Enable **Remote Login** ✓
3. Allow access for: **Only these users**
4. Add your user account
5. Note the SSH command shown (e.g., `ssh username@MacBook-Pro.local`)

### Step 3: Configure SSH for Key Authentication

Enable SSH key login:
```bash
sudo nano /etc/ssh/sshd_config
```

Find and uncomment these lines (remove the #):
```
PubkeyAuthentication yes
AuthorizedKeysFile     .ssh/authorized_keys
```

Save (Ctrl+X, Y, Enter) and restart SSH:
```bash
sudo launchctl stop com.openssh.sshd
sudo launchctl start com.openssh.sshd
```

### Step 4: Enable Wake-on-LAN

Allow Mac A to wake Mac B when sleeping:
```bash
sudo pmset -a womp 1
```

Find Mac B's MAC address for ethernet:
```bash
ifconfig en0 | grep ether
```

### Step 5: Create Required Directories

```bash
mkdir -p ~/IncomingPhotos ~/ProcessedPhotos ~/ImportReports
```

## Mac A Setup

### Step 1: Generate SSH Key

Create a dedicated key for the pipeline:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/pipeline_key -C "pipeline" -N ""
chmod 600 ~/.ssh/pipeline_key
```

### Step 2: Copy Key to Mac B

Display your public key:
```bash
cat ~/.ssh/pipeline_key.pub
```

Copy the entire output (starts with `ssh-ed25519`).

On Mac B, add the key:
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "paste-your-key-here" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### Step 3: Test Connection

From Mac A:
```bash
ssh -i ~/.ssh/pipeline_key username@mac-b.local
```

You should connect without a password prompt. Type `exit` to disconnect.

## Automator Workflow Setup (Mac B)

### Create the Import Workflow

1. Open **Automator** → **New** → **Folder Action**
2. Choose folder: `~/IncomingPhotos`
3. Add these actions in order:

#### Action 1: Run Shell Script (Validation)
- Shell: `/bin/bash`
- Pass input: **as arguments**
- Copy the validation script from `docs/automator-scripts/validate.sh`

#### Action 2: Get Folder Contents
- No configuration needed

#### Action 3: Filter Finder Items
- All of the following are true:
  - Kind **is** Image
  - Name **ends with** .heic **OR**
  - Name **ends with** .HEIC **OR**

#### Action 4: Import Files into Photos
- To Album: Leave empty
- Delete items after import: **UNCHECKED**

#### Action 5: Run Shell Script (Manifest)
- **⚠️ CRITICAL**: Right-click this action → **Ignore Input**
- Shell: `/bin/bash`
- Pass input: **as arguments** (even though ignoring)
- Copy the manifest script from `docs/automator-scripts/manifest.sh`

### Save and Enable

1. Save as: **"Import Photos Pipeline"**
2. Right-click `~/IncomingPhotos` in Finder
3. Services → **Folder Actions Setup**
4. Enable Folder Actions ✓
5. Select your workflow

### Important Permission

If the ‘Enable Folder Actions’ checkbox in the Folder Actions Setup dialog is greyed out, open System Settings → Privacy & Security → Extensions → Folder Actions and enable it there first

On first photo import, macOS will show:
> "FolderActionsDispatcher" wants access to control "Photos"

**You MUST click "Allow"** for the pipeline to work.

## Pipeline Configuration (Mac A)

The pipeline creates `data/pipeline_config.json` on first use. Update with your Mac B details:

```json
{
  "mac_b": {
    "host": "username@mac-b.local", <-- Update with correct host information
    "mac_address": "aa:bb:cc:dd:ee:ff", <-- Update with correct lan mac address
    "ssh_key_path": "~/.ssh/pipeline_key", <-- Verify if correct
    "wake_wait_time": 30,
    "connection_timeout": 300
  },
  "transfer": {
    "batch_size_limit": null,
    "timeout_seconds": 3600,
    "timeout_per_photo": 120,
    "retry_count": 3,
    "retry_delay": 10,
    "chunk_size": 32768
  },
  "paths": {
    "staging_dir": "~/ToSend",
    "remote_incoming": "~/IncomingPhotos",
    "remote_processed": "~/ProcessedPhotos",
    "remote_reports": "~/ImportReports",
    "local_reports": "~/reports"
  },
  "cleanup": {
    "keep_successful_days": 0,
    "keep_failed_days": 0,
    "clean_import_log": true,
    "clean_incoming_after_hours": 0.25,
    "startup_cleanup": true
  }
}
```

### Configuration Options

#### Connection Settings
- `host`: SSH connection string for Mac B
- `mac_address`: For Wake-on-LAN (from `ifconfig en0`)
- `wake_wait_time`: Seconds to wait after wake signal
- `connection_timeout`: Max seconds to wait for connection

#### Transfer Settings
- `batch_size_limit`: Max photos per batch (null = unlimited)
- `timeout_seconds`: Overall timeout (default 1 hour)
- `timeout_per_photo`: Per-photo timeout (default 2 minutes)
- `retry_count`: Transfer retry attempts
- `chunk_size`: SFTP transfer chunk size

#### Cleanup Settings
- `keep_successful_days`: Days to keep successful transfers (0 = immediate deletion)
- `keep_failed_days`: Days to keep failed transfers (0 = immediate deletion)
- `clean_import_log`: Clear log after each batch
- `clean_incoming_after_hours`: Clean orphaned files after N hours
- `startup_cleanup`: Clean old files on pipeline start

## Using the Pipeline

## First Run Behavior

When you first click "Send to Photos", the pipeline will:

1. **Automatically create** `data/pipeline_config.json` with defaults
2. **Show an error** telling you to edit the file
3. **Not transfer any photos** until configured

You'll see this error:

### Basic Workflow

1. Edit and **save** metadata for photos
2. Select photos (single or multiple in grid view)
3. Click **"Send to Photos"**
4. Monitor progress in the status area
5. Verify import in Apple Photos on Mac B

### What Happens During Transfer

1. **Wake Mac B** (if sleeping)
2. **Stage photos** in local `ToSend` directory
3. **Transfer via SFTP** to Mac B
4. **Trigger Automator** with special files
5. **Import to Photos** automatically
6. **Receive confirmation** when complete
7. **Clean up** transferred files

### Transfer Progress

The interface shows detailed progress:
```
Processing batch 20250117_143022...
  IMG_001.heic: 45% (2,340,123/5,200,000 bytes)
  Current file: 3 of 25
```

### Timeouts

Dynamic timeout calculation:
- 2 minutes per photo
- Maximum 1 hour total
- Configurable in pipeline_config.json

## File Structure

### Mac A (Source)
```
your-photos/                    # Original photos (unchanged)
../ToSend/                      # Staging directory
    └── batch_20250117_*/       # One folder per transfer
        ├── IMG_001.heic        # Copies being sent
        └── staged_manifest.json # Transfer record
```

### Mac B (Destination)
```
~/IncomingPhotos/               # Automator watches this
    └── 20250117_143022/        # Incoming batch
        ├── IMG_001.heic        # Transferred photos
        ├── transfer_manifest.json
        └── .ready              # Triggers Automator

~/ProcessedPhotos/              # After import (based on cleanup settings)
~/ImportReports/                # Logs and confirmations
    ├── import.log              # Automator activity
    └── manifest_*.json         # Import confirmations
```

## Troubleshooting

### SSH Issues

#### Connection Refused
```bash
# Debug with verbose mode
ssh -vvv -i ~/.ssh/pipeline_key user@mac-b.local
```

Common causes:
1. Remote Login not enabled
2. User not in allowed list
3. Firewall blocking SSH

#### Permission Denied
1. Check `PubkeyAuthentication yes` in sshd_config
2. Verify key permissions: `ls -la ~/.ssh/`
   - `.ssh` directory: 700
   - `authorized_keys`: 600
   - Private key: 600

### Import Issues

#### Photos Not Importing
1. **Check for permission dialog** on first run
2. Verify Automator enabled: Right-click `~/IncomingPhotos` → Services
3. Check `~/ImportReports/import.log` for errors
4. Ensure final script has **"Ignore Input"** selected

#### Stuck at "Waiting for manifest"
Usually means Automator didn't create the completion file:
1. Check if photos actually imported to Apple Photos
2. Verify Python works: `python3 --version` on Mac B
3. Check workflow structure - final script must be disconnected

### Performance Issues

#### Slow Transfers
- Verify ethernet connection (not WiFi)
- Check network congestion
- Consider setting `batch_size_limit` for very large batches
- Typical speed: 1-2 MB/s per photo

#### Timeouts
- Increase `timeout_per_photo` for slow networks
- Reduce batch size
- Check Mac B isn't sleeping during transfer

## Removing the Pipeline

### On Mac B
1. Disable Folder Actions on `~/IncomingPhotos`
2. Delete the Automator workflow
3. Remove directories:
   ```bash
   rm -rf ~/IncomingPhotos ~/ProcessedPhotos ~/ImportReports
   ```
4. Remove SSH key from `~/.ssh/authorized_keys`
5. Optionally disable Remote Login and Wake-on-LAN

### On Mac A
1. Remove SSH keys:
   ```bash
   rm -f ~/.ssh/pipeline_key*
   ```
2. Remove configuration:
   ```bash
   rm -f data/pipeline_config.json
   ```
3. Remove staging directory:
   ```bash
   rm -rf ../ToSend
   ```

## Security Notes

- **SSH Keys**: Uses key authentication (no passwords transmitted)
- **Local Network Only**: No internet routing required
- **Auto-Accept Host Keys**: `AutoAddPolicy` accepts any SSH host key for convenience
- **File Cleanup**: Transferred files deleted based on retention settings
- **No Cloud Services**: Direct Mac-to-Mac transfer only

For production use, consider manually verifying SSH host keys instead of auto-accepting.

## Tips and Best Practices

1. **Test with small batches** before processing entire collections
2. **Monitor first transfer** to ensure permissions are granted
3. **Use ethernet** for reliability and speed
4. **Keep Mac B awake** during large transfers
5. **Check Photos preferences** for duplicate handling
6. **Verify disk space** on both Macs before large transfers