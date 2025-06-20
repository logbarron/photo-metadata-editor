# Setup Guide

This guide covers installing and configuring the Photo Metadata Editor.

## Prerequisites

Before installing, ensure you have:

- **macOS** (tested on Sequoia 15.5, requires macOS 10.15+)
- **Xcode Command Line Tools** installed
- **Photos to process** in HEIC format
- **Backup of your photos** (this tool modifies files permanently)

To install Xcode Command Line Tools:
```bash
xcode-select --install
```

## Installation

### Step 1: Install uv Package Manager

[uv](https://docs.astral.sh/uv/) manages Python dependencies automatically.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After installation, restart your terminal or run:
```bash
source ~/.zshrc  # or ~/.bashrc for bash users
```

### Step 2: Download the Tool

```bash
git clone https://github.com/logbarron/photo-metadata-editor
cd photo-metadata-editor
```

### Step 3: First Run

The first run creates a configuration file:

```bash
./code/photo_metadata_editor.py /path/to/your/photos
```

You'll see:
```
📝 Creating .env file with default values...
✓ Created /path/to/code/.env

⚠️  IMPORTANT: Edit .env with your camera/scanner information!
   Then run this command again.
```

### Step 4: Configure Your Scanner

Edit `code/.env` with your scanner/camera details:

```bash
nano code/.env  # Opens in TextEdit
```

Update these values:
```ini
# Camera/scanner that digitized the photos
CAMERA_MAKE=YourCamera/ScannerBrand
CAMERA_MODEL=YourCamera/ScannerModel
```

Common examples:
- Fujifilm Camera: `CAMERA_MAKE=FUJIFILM` `CAMERA_MODEL=GFX100S II`
- Epson scanner: `CAMERA_MAKE=Epson` `CAMERA_MODEL=Perfection V850`

> **Note**: If your photos already have real camera metadata (not from your scanner), the tool automatically preserves it.

### Step 5: Run Again

After configuring, run from the tool directory:

```bash
./code/photo_metadata_editor.py /path/to/your/photos
```

## What Happens on First Run

The tool automatically:

1. **Downloads ExifTool** (v13.30, ~3MB)
   - Required for reading/writing metadata
   - Installs to `tools/exiftool/`

2. **Creates SQLite database** (`data/photo_metadata.db`)
   - Indexes all photos in the directory
   - Caches thumbnails for performance
   - Stores location history

3. **Generates thumbnails**
   - Uses 10 parallel workers by default
   - Creates two sizes: 120x120 (grid) and 800x800 (preview)
   - Shows progress: "Generating thumbnails: 523/523 (100%)"
   - Cached in database for fast access

4. **Opens web interface**
   - Launches at http://localhost:5555
   - Interface opens automatically

First run processing time depends on photo count (approximate):
- 100 photos: ~1 minute
- 1,000 photos: ~3-5 minutes  
- 10,000 photos: ~20-30 minutes (tested maximum)

## Directory Structure

```
photo-metadata-editor/
├── code/
│   ├── photo_metadata_editor.py    # Main application
│   ├── photo_editor_ui.html        # Web interface
│   └── .env                        # Your configuration (created)
├── data/                           # Runtime data (created)
│   ├── photo_metadata.db           # Photo index and thumbnails
│   ├── apple_geocode_cache.csv     # Location search cache (created on use)
│   └── pipeline_config.json        # Pipeline settings (if using Part 2)
└── tools/                          # External tools (created)
    └── exiftool/                   # Metadata tool (auto-downloaded)
```

## Configuration Options

The `.env` file supports these settings:

### Required Settings
```ini
# Your scanner information (required)
CAMERA_MAKE=YourBrand
CAMERA_MODEL=YourModel
IMAGE_DESCRIPTION=Camera Scanned Image
```

### Performance Tuning
```ini
# Parallel processing (adjust based on CPU)
THUMBNAIL_WORKERS=10     # Thumbnail generation threads
METADATA_WORKERS=10      # Metadata processing threads

# Cache sizes (number of entries)
METADATA_CACHE_SIZE=1000
THUMBNAIL_CACHE_SIZE=1000
```

### Other Settings
```ini
# Web interface
WEB_PORT=5555           # Change if port conflict

# Metadata keywords: 
DATE_KEYWORD=MissingDate
LOCATION_KEYWORD=MissingLocation

# Unknown date values
UNKNOWN_YEAR=1901
UNKNOWN_MONTH=01
UNKNOWN_DAY=02

# ExifTool version
EXIFTOOL_VERSION=13.30
```

**Note about Keywords**: The DATE_KEYWORD and LOCATION_KEYWORD are tags that the tool automatically adds to photos missing that information. These appear as keywords in Apple Photos, making it easy to find incomplete photos.

## Optional: Offline Location Data

For offline city lookup, download the US cities database:

1. Visit https://simplemaps.com/data/us-cities
2. Download the "Basic" version (free with attribution)
3. Save as `data/uscities.csv`

Without this file, the tool uses Apple's online geocoding (recommended).

## Troubleshooting Installation

### Port Already in Use

If you see "Address already in use":
1. Edit `code/.env`
2. Change `WEB_PORT=5555` to another port (e.g., 8080, 8888)
3. Run again

### Permission Denied

Make the script executable:
```bash
chmod +x code/photo_metadata_editor.py
```

### ExifTool Download Failed

If automatic download fails:
1. Download from https://exiftool.org
2. Extract to `tools/`
3. Rename folder to `exiftool`
4. Make executable: `chmod +x tools/exiftool/exiftool`

### No Photos Found

Ensure:
- Photos are in HEIC format (not JPEG, PNG, or RAW)
- Path is correct and uses forward slashes
- You have read permissions on the directory

### Python Version Issues

The tool requires Python 3.11+. Check your version:
```bash
python3 --version
```

If outdated, uv will handle it automatically.

## Two Parts of This Tool

This tool has two distinct components:

1. **Metadata Editor** (This guide) - Fix dates/locations on one Mac
2. **Pipeline System** (Optional) - Transfer photos between two Macs

Most users only need Part 1. See [Pipeline Setup](pipeline.md) if you need to transfer photos to a different Mac.

## Next Steps

Once setup is complete:
1. Read the [User Guide](user-guide.md) to learn the interface
2. Process a small test batch first (10-20 photos)
3. Make a backup before processing your entire collection
4. Set up [Pipeline](pipeline.md) only if using multiple Macs

## Important Warnings

⚠️ **File Modification Warning**: This tool permanently modifies your photo files. Original metadata is overwritten and cannot be recovered. Always maintain backups before processing.

⚠️ **Format Limitation**: Only HEIC format is supported.
