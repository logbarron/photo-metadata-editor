# Mac B Pipeline Setup - Complete Undo Guide

This guide will help you completely remove all changes made for the photo import pipeline on Mac B.

## Quick Checklist
- [ ] Remove Automator workflow
- [ ] Disable Folder Actions
- [ ] Delete created directories
- [ ] Remove SSH keys
- [ ] Disable Wake-on-LAN (if enabled for this)
- [ ] Disable Remote Login (if enabled for this)
- [ ] Remove pipeline user (if created)
- [ ] Clean up any test photos imported

## 1. Remove Automator Workflow and Folder Actions

### Disable Folder Actions on the Directory
```bash
# Method 1: Via Finder
# Right-click on ~/IncomingPhotos folder
# → Services → Folder Actions Setup
# → Uncheck the folder or remove the workflow

# Method 2: Via command line
# WARNING: This removes ALL folder actions, not just the pipeline one
# /System/Library/CoreServices/Folder\ Actions\ Dispatcher.app/Contents/Resources/FASettingsTool -r

# Better: Just remove the specific folder's action via Finder method above
```

### Delete the Automator Workflow
```bash
# The workflow is typically stored in:
rm -f ~/Library/Workflows/Applications/Folder\ Actions/Import\ Photos\ Pipeline.workflow

# Or check in iCloud if you use iCloud Drive:
rm -f ~/Library/Mobile\ Documents/com~apple~Automator/Documents/Import\ Photos\ Pipeline.workflow

# Or if system-wide:
sudo rm -f /Library/Workflows/Applications/Folder\ Actions/Import\ Photos\ Pipeline.workflow

# Check for any temporary helper scripts:
rm -f ~/ImportReports/.map_files.py
```

### Disable Folder Actions Globally (if you enabled it)
```bash
# System Preferences → Extensions → Folder Actions
# Uncheck "Enable Folder Actions"
```

## 2. Remove Created Directories

```bash
# Remove all pipeline directories and their contents
rm -rf ~/IncomingPhotos
rm -rf ~/ProcessedPhotos
rm -rf ~/ImportReports

# Note: ~/ToSend is on Mac A, not Mac B
```

### Directory Contents Being Removed

**Note**: With auto-cleanup enabled (default), these directories are likely already empty.

**~/IncomingPhotos/** may contain:
- Orphaned batch folders from interrupted transfers (cleaned after 15 minutes)

**~/ProcessedPhotos/** may contain:
- Empty (all batches auto-deleted after import with default settings)

**~/ImportReports/** may contain:
- import.log (truncated after each batch with default settings)
- No manifest files (auto-deleted with zero retention)

If cleanup was disabled, they would contain:
- Batch folders (YYYYMMDD_HHMMSS/)
- Transferred photos
- transfer_manifest.json files
- .ready and .trigger_* files
- manifest_*.json files

## 3. Remove SSH Keys and Access

### Remove Authorized Keys Entry

**Important**: Do this in the user account where you added the SSH key (either your regular user or the pipeline user if created)

```bash
# Edit the authorized_keys file
nano ~/.ssh/authorized_keys

# Remove the line that contains "pipeline" at the end
# (It will look like: ssh-ed25519 AAAAC3... pipeline)

# Or if it's the only key, you can remove the whole file:
rm ~/.ssh/authorized_keys

# If the .ssh directory is now empty and was created for this:
rmdir ~/.ssh
```

### On Mac A (to clean up there too):
```bash
# Remove the pipeline SSH key pair
rm -f ~/.ssh/pipeline_key
rm -f ~/.ssh/pipeline_key.pub

# Remove pipeline configuration
rm -f data/pipeline_config.json

# Remove staging directory and any leftover batches
rm -rf ../ToSend
```

## 4. Revert System Settings

### Disable Wake-on-LAN (if you enabled it)
```bash
# Check current setting first:
pmset -g | grep womp

# If it shows "womp 1" and you want to disable:
sudo pmset -a womp 0

# Verify it's disabled:
pmset -g | grep womp
# Should show: womp                 0
```

### Disable Remote Login (if you enabled it for this)

**⚠️ Only disable if you enabled it specifically for the pipeline and don't need SSH for other purposes**

```bash
# Via System Preferences:
# System Preferences → Sharing → Remote Login ☐ (uncheck)

# Or via command line:
sudo systemsetup -setremotelogin off

# Check status:
sudo systemsetup -getremotelogin
# Should show: Remote Login: Off
```

## 5. Remove Pipeline User (if created)

**⚠️ Only do this if you created a dedicated "pipeline" user**

```bash
# First, make sure you're not logged in as the pipeline user!

# Method 1: Via System Preferences
# System Preferences → Users & Groups
# Select "pipeline" user → Click [-] button

# Method 2: Via command line (requires admin)
sudo dscl . -delete /Users/pipeline

# Also remove the home directory if it wasn't automatically removed:
sudo rm -rf /Users/pipeline
```

## 6. Clean Up Photos.app

If you imported test photos:

1. Open Photos.app
2. Find any test imports (check "Imports" or "Recently Added")
3. Select and delete test photos
4. Empty Photos trash: Photos → Empty Trash

### Remove Import History
```bash
# Photos stores import history in its database
# There's no easy way to clean this without affecting other imports
# The imported photos deletion above is usually sufficient
```

## 7. Clean Up Logs and Caches

```bash
# Remove any import logs
rm -f ~/ImportReports/*.log
rm -f ~/ImportReports/manifest_*.json
rm -f ~/ImportReports/manifest_*.txt  # Old text format if any
rm -f ~/ImportReports/.manifest_*_tmp.json  # Temporary files

# Remove any cached data
rm -f ~/ImportReports/apple_geocode_cache.csv

# Clear any console logs related to Automator
# (Optional - these will rotate out naturally)
```

## 8. Network Configuration (if modified)

If you made any firewall exceptions:
```bash
# System Preferences → Security & Privacy → Firewall → Firewall Options
# Remove any rules added for SSH or pipeline
```

## 9. Final Verification

Run these checks to ensure everything is back to normal:

```bash
# Check no pipeline directories exist:
ls -la ~ | grep -E "(IncomingPhotos|ProcessedPhotos|ImportReports)"

# Check SSH is disabled (if you disabled it):
sudo systemsetup -getremotelogin

# Check Wake-on-LAN is disabled (if you disabled it):
pmset -g | grep womp

# Check no Folder Actions:
/System/Library/CoreServices/Folder\ Actions\ Dispatcher.app/Contents/Resources/FASettingsTool -l

# Check no pipeline user exists (if you created one):
dscl . -list /Users | grep pipeline

# Check authorized_keys is clean:
grep -c "pipeline" ~/.ssh/authorized_keys 2>/dev/null || echo "0"
# Should show: 0 (or file not found error)
```

## 10. Optional: System State Snapshot

For future reference, you might want to capture current state BEFORE making changes:

```bash
# Before setup, run:
echo "=== System State Before Pipeline Setup ===" > ~/Desktop/mac_b_state_before.txt
echo "Remote Login:" >> ~/Desktop/mac_b_state_before.txt
sudo systemsetup -getremotelogin >> ~/Desktop/mac_b_state_before.txt
echo -e "\nWake on LAN:" >> ~/Desktop/mac_b_state_before.txt
pmset -g | grep womp >> ~/Desktop/mac_b_state_before.txt
echo -e "\nUsers:" >> ~/Desktop/mac_b_state_before.txt
dscl . -list /Users | grep -v "^_" >> ~/Desktop/mac_b_state_before.txt
echo -e "\nSSH Keys:" >> ~/Desktop/mac_b_state_before.txt
ls -la ~/.ssh/ 2>/dev/null >> ~/Desktop/mac_b_state_before.txt
echo -e "\nFolder Actions:" >> ~/Desktop/mac_b_state_before.txt
/System/Library/CoreServices/Folder\ Actions\ Dispatcher.app/Contents/Resources/FASettingsTool -l >> ~/Desktop/mac_b_state_before.txt
```

## Notes

- **Imported Photos**: This guide doesn't remove photos already imported to Photos.app. You'll need to manually identify and remove those if needed.
- **Time Machine**: If Time Machine backed up during setup, those backups will contain the pipeline configuration
- **iCloud**: If any folders were in iCloud Drive, changes may have synced to other devices

## Emergency Reset

If something goes wrong and you need a quick reset:

```bash
# Quick cleanup script (run with caution):
#!/bin/bash
rm -rf ~/IncomingPhotos ~/ProcessedPhotos ~/ImportReports
rm -f ~/Library/Workflows/Applications/Folder\ Actions/Import\ Photos\ Pipeline.workflow
# Don't auto-remove SSH keys or change system settings - do those manually
```

---

Remember: It's always safer to check each item before removing it, especially for system settings that might have been enabled for other purposes!