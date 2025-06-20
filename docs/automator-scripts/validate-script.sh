#!/bin/bash
# Automator Script 1: Validate incoming photo batch
# This script goes in the first "Run Shell Script" action

# Set error handling
set -e

# Log function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> ~/ImportReports/import.log
}

log "=== Folder action triggered ==="
log "Triggered at exactly: $(date '+%Y-%m-%d %H:%M:%S.%3N')"
log "Triggered with arguments: $@"
log "Contents of IncomingPhotos: $(ls -la ~/IncomingPhotos/)"

# Find the newest batch directory that has a .ready file
BATCH_DIR=""
for dir in ~/IncomingPhotos/20*_*; do
    if [ -d "$dir" ] && [ -f "$dir/.ready" ]; then
        # Check if this batch hasn't been processed yet
        BATCH_ID=$(basename "$dir")
        if [ ! -f ~/ImportReports/manifest_${BATCH_ID}.json ]; then
            BATCH_DIR="$dir"
            break
        fi
    fi
done

if [ -z "$BATCH_DIR" ]; then
    log "No unprocessed batch directories found with .ready file"
    # Exit without error but without outputting anything
    exit 0
fi

BATCH_ID=$(basename "$BATCH_DIR")
log "Found unprocessed batch: $BATCH_ID in $BATCH_DIR"

# Check for transfer manifest
TRANSFER_MANIFEST="$BATCH_DIR/transfer_manifest.json"
if [ ! -f "$TRANSFER_MANIFEST" ]; then
    log "ERROR - No transfer manifest found for batch $BATCH_ID"
    exit 1
fi

log "Batch $BATCH_ID validated, proceeding to import"

# Pass the batch directory to next action
echo "$BATCH_DIR"