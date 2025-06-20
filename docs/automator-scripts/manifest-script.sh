#!/bin/bash
# Automator Script 2: Generate import manifest after Photos import
# This script goes in the final "Run Shell Script" action
# IMPORTANT: Right-click this action and select "Ignore Input"

# Set error handling
set -e

# Log function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> ~/ImportReports/import.log
}

log "=== Manifest generation script started ==="
log "Import completed at: $(date '+%Y-%m-%d %H:%M:%S.%3N')"

# Find the batch directory we just processed
# Look for the newest batch directory that has a .ready file but no manifest yet
BATCH_DIR=""
for dir in ~/IncomingPhotos/20*_*; do
    if [ -d "$dir" ] && [ -f "$dir/.ready" ]; then
        BATCH_ID=$(basename "$dir")
        # Check if manifest doesn't exist yet
        if [ ! -f ~/ImportReports/manifest_${BATCH_ID}.json ]; then
            BATCH_DIR="$dir"
            break
        fi
    fi
done

if [ -z "$BATCH_DIR" ]; then
    log "ERROR - No batch directory found that needs manifest"
    exit 1
fi

BATCH_ID=$(basename "$BATCH_DIR")
log "Creating manifest for batch: $BATCH_ID"

# Get list of image files that were imported
IMPORTED_FILES=()
for ext in heic HEIC jpg jpeg JPG JPEG; do
    for file in "$BATCH_DIR"/*.$ext; do
        if [ -f "$file" ]; then
            IMPORTED_FILES+=("$file")
        fi
    done
done

if [ ${#IMPORTED_FILES[@]} -eq 0 ]; then
    log "ERROR - No image files found in batch"
    exit 1
fi

log "Found ${#IMPORTED_FILES[@]} image files"

# Read transfer manifest to get original paths
TRANSFER_MANIFEST="$BATCH_DIR/transfer_manifest.json"
if [ ! -f "$TRANSFER_MANIFEST" ]; then
    log "ERROR - Transfer manifest not found"
    exit 1
fi

# Create temporary file for atomic write
TEMP_MANIFEST="$HOME/ImportReports/.manifest_${BATCH_ID}_tmp.json"
FINAL_MANIFEST="$HOME/ImportReports/manifest_${BATCH_ID}.json"

# Create a simple helper script to do the mapping
HELPER_SCRIPT="$HOME/ImportReports/.map_files.py"
cat > "$HELPER_SCRIPT" << 'PYTHON_EOF'
#!/usr/bin/env python3
import json
import sys
import os

# Read transfer manifest
with open(sys.argv[1]) as f:
    transfer_manifest = json.load(f)

# Create lookup by both full path and basename
path_map = {}
basename_map = {}
for file_info in transfer_manifest.get('files', []):
    remote_path = file_info['remote_path']
    # Normalize the path to handle ~ expansion
    if remote_path.startswith('~'):
        remote_path = remote_path.replace('~', os.path.expanduser('~'), 1)
    path_map[remote_path] = file_info['original_path']
    # Also map by basename as fallback
    basename = os.path.basename(remote_path)
    if basename not in basename_map:
        basename_map[basename] = []
    basename_map[basename].append(file_info['original_path'])

# Read imported files from stdin
imported_files = []
warnings = []

for line in sys.stdin:
    filepath = line.strip()
    original_path = None
    
    # Try exact path match first
    if filepath in path_map:
        original_path = path_map[filepath]
    else:
        # Try basename match
        basename = os.path.basename(filepath)
        if basename in basename_map:
            candidates = basename_map[basename]
            if len(candidates) == 1:
                # Unique basename, safe to use
                original_path = candidates[0]
            else:
                # Multiple files with same basename - use first and warn
                original_path = candidates[0]
                warnings.append(f"Multiple candidates for {basename}, using {original_path}")
    
    if original_path:
        imported_files.append({
            'filename': os.path.basename(filepath),
            'original_path': original_path,
            'import_time': sys.argv[2]
        })
    else:
        # Complete fallback - shouldn't happen
        imported_files.append({
            'filename': os.path.basename(filepath),
            'original_path': filepath,
            'import_time': sys.argv[2],
            'warning': 'Could not map to original path'
        })
        warnings.append(f"No mapping found for {filepath}")

# Output complete manifest
manifest = {
    'batch_id': sys.argv[3],
    'timestamp': sys.argv[2],
    'count': len(imported_files),
    'files': imported_files
}

if warnings:
    manifest['warnings'] = warnings

print(json.dumps(manifest, indent=2))
PYTHON_EOF

chmod +x "$HELPER_SCRIPT"

# Pass all imported file paths to the helper script
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
printf '%s\n' "${IMPORTED_FILES[@]}" | python3 "$HELPER_SCRIPT" "$TRANSFER_MANIFEST" "$TIMESTAMP" "$BATCH_ID" > "$TEMP_MANIFEST"

# Atomic move to final location
mv "$TEMP_MANIFEST" "$FINAL_MANIFEST"

# Clean up helper script
rm -f "$HELPER_SCRIPT"

log "Manifest created: $FINAL_MANIFEST"
log "Successfully imported ${#IMPORTED_FILES[@]} files from batch $BATCH_ID"

# Move batch to processed (with error handling)
PROCESSED_DIR="$HOME/ProcessedPhotos/$BATCH_ID"
if mkdir -p "$PROCESSED_DIR"; then
    # Move files preserving structure
    for file in "$BATCH_DIR"/*; do
        if [ -f "$file" ]; then
            mv "$file" "$PROCESSED_DIR/" 2>/dev/null || true
        fi
    done
    
    # Remove empty batch directory
    rmdir "$BATCH_DIR" 2>/dev/null || true
    
    log "Batch $BATCH_ID moved to processed"
else
    log "WARNING - Could not move batch to processed"
fi

log "=== Manifest generation script completed ==="
echo "Import complete for batch $BATCH_ID"