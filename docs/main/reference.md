# Technical Reference

Architecture, configuration, troubleshooting, and performance optimization.

## Architecture Overview

### System Components

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Web Browser   │────▶│ Waitress Server │────▶│   SQLite    │
│  (JavaScript)   │◀────│    (Python)     │◀────│  Database   │
└─────────────────┘     └─────────────────┘     └─────────────┘
                               │
                               ├──────────────┐
                               ▼              ▼
                        ┌──────────────┐ ┌──────────────┐
                        │   ExifTool   │ │  Mistral-7B  │
                        │ (Metadata)   │ │   (Parser)   │
                        └──────────────┘ └──────────────┘
```

### Data Flow

1. **Photo Scanning**: Parallel workers index photos into SQLite
2. **Filename Parsing**: Mistral-7B analyzes filenames for dates/locations
3. **Thumbnail Generation**: 10 workers create cached thumbnails
4. **User Edits**: Web interface updates via REST API
5. **File Writing**: ExifTool modifies HEIC files directly
6. **Cache Management**: LRU eviction at 1000 entries (except LLM results)

## Performance Optimization

### Database Configuration

The application uses SQLite with these optimizations:
```sql
PRAGMA journal_mode=WAL      -- Write-ahead logging
PRAGMA synchronous=NORMAL    -- Balanced durability
PRAGMA cache_size=10000      -- 10k pages in memory
PRAGMA busy_timeout=10000    -- 10 second timeout
```

### Parallel Processing

Configure worker counts in `.env`:

| Setting | Default | Description | Recommendation |
|---------|---------|-------------|----------------|
| `THUMBNAIL_WORKERS` | 10 | Thumbnail generation threads | Set to CPU core count |
| `METADATA_WORKERS` | 10 | Metadata processing threads | Set to CPU core count |

For a 6-core Mac: set both to 6
For a 10-core Mac: keep at 10

### Cache Configuration

| Cache Type | Default Size | Eviction | Location |
|------------|--------------|----------|----------|
| Metadata | 1000 entries | LRU, removes oldest 20 | Memory |
| Thumbnails | 1000 entries | LRU, removes oldest 20 | Memory + DB |

Increase for better performance with large collections:
```ini
METADATA_CACHE_SIZE=2000
THUMBNAIL_CACHE_SIZE=2000
```

## Configuration Reference

### Environment Variables (.env)

#### Required Settings
```ini
CAMERA_MAKE=YourScanner        # Scanner/camera brand
CAMERA_MODEL=YourModel         # Scanner/camera model
IMAGE_DESCRIPTION=Camera Scanned Image
```

#### Performance Settings
```ini
THUMBNAIL_WORKERS=10           # Parallel thumbnail threads
METADATA_WORKERS=10            # Parallel metadata threads
METADATA_CACHE_SIZE=1000       # Memory cache entries
THUMBNAIL_CACHE_SIZE=1000      # Memory cache entries
```

#### Application Settings
```ini
WEB_PORT=5555                  # Web interface port
DATE_KEYWORD=MissingDate       # Tag for photos needing date
LOCATION_KEYWORD=MissingLocation # Tag for photos needing location
LLM_PARSER_ENABLED=true        # LLM filename parsing (default: true)
```

#### Unknown Values
```ini
UNKNOWN_YEAR=1901              # Year for unknown dates
UNKNOWN_MONTH=01               # Month for unknown dates
UNKNOWN_DAY=02                 # Day for unknown dates
```

#### System Settings
```ini
EXIFTOOL_VERSION=13.30         # ExifTool version to download
```

### Pipeline Configuration (pipeline_config.json)

Created on first pipeline use:

```json
{
  "mac_b": {
    "host": "username@hostname.local",
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ssh_key_path": "~/.ssh/pipeline_key",
    "wake_wait_time": 30,
    "connection_timeout": 300
  },
  "transfer": {
    "batch_size_limit": null,      // null = unlimited
    "timeout_seconds": 3600,       // 1 hour max
    "timeout_per_photo": 120,      // 2 min per photo
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
    "keep_successful_days": 0,     // 0 = delete immediately
    "keep_failed_days": 0,         // 0 = delete immediately
    "clean_import_log": true,      // Truncate after each batch
    "clean_incoming_after_hours": 0.25,  // 15 minutes
    "startup_cleanup": true        // Clean on pipeline start
  }
}
```
### LLM Performance

The Mistral-7B model processes filenames with these characteristics:

| Metric | Value | Description |
|--------|-------|-------------|
| First photo | ~6 seconds | Model loading + inference |
| Second photo | ~8 seconds |  Inference + next photo inference |
| Subsequent photos | <1 second | Pre-fetched or cached |
| Model size | 4GB | One-time download |
| RAM usage | ~4GB | When model is active |
| Worker threads | 2 | Delayed spawning to prevent contention |
| Cache | Permanent | Results stored in database |

Pre-fetching strategy:
- Current photo: Immediate (high priority)
- Next 3 photos: Background (low priority)
- Already processed: Instant (from cache or db)

## Troubleshooting

### Metadata Editor Issues

#### Photos Not Appearing
**Symptoms**: No photos in interface, all filters show 0
**Causes & Solutions**:
1. Wrong format - Only HEIC files are supported
2. Wrong path - Use forward slashes: `/Users/name/Photos`
3. No permissions - Check read access: `ls -la /path/to/photos`

#### Date Suggestions Not Working
**Symptoms**: No blue suggestion button appears
**Solutions**:
1. Rename files to include dates: `July_4_1995_description.heic`
2. Supported patterns:
   - `Month_Day_Year` (July_4_1995)
   - `YYYY-MM-DD` (1995-07-04)
   - `Month_Year` (July_1995)
   - `Year` only (1995)

#### Location Search Not Working
**Symptoms**: No results or timeout
**Solutions**:
1. Check internet connection (requires Apple Maps)
2. Wait 1 second between searches (rate limit)
3. Try simpler queries: "Chicago" instead of full address
4. For offline use, add `data/uscities.csv`

#### Save Button Disabled
**Symptoms**: Can't save changes
**Causes**:
1. No changes made yet
2. File permissions issue
3. Database locked (close other instances)

#### Thumbnails Not Loading
**Symptoms**: Broken image icons
**Solutions**:
1. Check disk space (need ~1GB for 1000 photos)
2. Clear cache: Delete `data/photo_metadata.db` and restart
3. Check console for errors (Cmd+Option+I in browser)

### Pipeline Issues

#### SSH Connection Failed
**Symptoms**: "Failed to connect to Mac B"
**Debug Steps**:
```bash
# Test basic connection
ssh -vvv -i ~/.ssh/pipeline_key user@mac-b.local

# Common issues:
# 1. PubkeyAuthentication not enabled
# 2. Wrong key permissions (must be 600)
# 3. Hostname changed
# 4. User not in allowed users
```

#### Photos Not Importing
**Symptoms**: Transfer succeeds but no import
**Solutions**:
1. **First time**: Look for permission dialog in Photos app
2. Check Automator workflow enabled on `~/IncomingPhotos`
3. Verify final script has "Ignore Input" selected
4. Check `~/ImportReports/import.log` for errors

#### Pipeline Stuck "Waiting for manifest"
**Symptoms**: Progress stops at manifest wait
**Causes**:
1. Automator workflow not triggering
2. Python not available on Mac B
3. Manifest script connected to import action
**Fix**: Ensure final Automator script has "Ignore Input" selected

#### Wake-on-LAN Not Working
**Requirements**:
1. Both Macs on ethernet (not WiFi)
2. Correct MAC address in config
3. Wake for network access enabled
4. Same network segment

### Performance Issues

#### Slow Initial Scan
**Normal for large collections**. Speed up by:
1. Increasing `METADATA_WORKERS` to match CPU cores
2. Using SSD storage for photos
3. Closing other applications

#### LLM Parsing Issues

##### Model Download Failed
**Symptoms**: Stuck at "Downloading model..." or error message
**Solutions**:
1. Check internet connection (4GB download required)
2. Check disk space in home directory (~4GB needed)
3. Delete .llm_cache folder in /data
4. Disable if needed: Set `LLM_PARSER_ENABLED=false` in `.env`

##### "Analyzing..." Never Completes
**Symptoms**: Suggestion buttons stuck on "Analyzing..."
**Causes**:
1. Model failed to load (check console for errors)
2. Not enough RAM (need ~4GB free)
3. Background worker crashed
**Solutions**:
1. Restart the application
2. Check Activity Monitor for memory usage
3. Disable other applications to free RAM

##### Suggestions Not Appearing
**Symptoms**: No blue suggestion buttons even with clear dates in filename
**Note**: The LM & Regex needs recognizable patterns. Examples that work:
- "Birthday_Chicago_July_4_1995.heic" ✓
- "Grandma 80th birthday Chicago 1995.heic" ✓  
- "IMG_1234.heic" ✗ (no context to parse)
- "Scan0001.heic" ✗ (just numbers)

## File Structure Details

### Database Schema

`photo_metadata.db` key tables:
- **photos**: Main photo metadata and state
  - Includes LLM suggestion cache columns
  - Stores parsing confidence and reasoning
- **locations**: Saved locations with usage count
- **thumbnails**: Cached thumbnail data
- **pipeline_queue**: Transfer queue (if using pipeline)
- **pipeline_status**: Transfer history

### Metadata Written

ExifTool tags modified:
```
-DateTimeOriginal    # When photo was taken
-CreateDate          # File creation date
-ModifyDate          # File modification date
-Make                # Camera manufacturer
-Model               # Camera model
-GPSLatitude         # Latitude
-GPSLongitude        # Longitude
-GPSLatitudeRef      # N/S
-GPSLongitudeRef     # E/W
-XMP:City            # City name
-XMP:State           # State/Province
-XMP:Country         # Country (always "United States")
-Keywords            # Status tracking tags (MissingDate, MissingLocation)
-Subject             # Same tags (for compatibility)
```

## Security Considerations

### Local Processing
- All photo processing happens locally
- Only external service: Apple Maps geocoding
- No analytics or telemetry
- No automatic updates

### SSH Security (Pipeline)
- Key-based authentication only
- No password authentication
- AutoAddPolicy accepts any host key (convenience over security)
- Consider manually verifying host keys for production use

### File Safety
- Original files modified in-place
- No automatic backups created
- Database can be corrupted if interrupted
- Always maintain external backups

## Additional Topics

### City Database
1. Download the Basic version (free with attribution) https://simplemaps.com/data/us-cities
2. Place at `data/uscities.csv`
3. Provides offline city lookup
4. Falls back to Apple Maps for landmarks

### Batch Processing
- Use grid view for visual grouping
- Process by event or location
- Take advantage of frequent locations
- Use sequence sort for album order

### Network Optimization (Pipeline)
- Use gigabit ethernet for best performance
- Typical transfer: 1-2 MB/s per photo
- Batch transfers reduce overhead
- Consider `batch_size_limit` for very large collections

### LLM Configuration

While the default settings work well, advanced users can tune behavior:

1. **Disable LLM**: Set `LLM_PARSER_ENABLED=false` in `.env`
2. **Clear parsing cache**: 
   ```sql
   UPDATE photos SET suggestion_parsed_at = NULL;
3. **Force re-parse**: Delete suggestion cache or database and restart
4. **Change Prompt**: Adjust in main .py. Prompt is very temperamental, proceed with caution. 

The model runs with these settings:

4-bit quantization for efficiency
GPU acceleration when available
400 token context window
Temperature 0.1 for consistent results