# User Guide

Guide to fixing dates and locations on digitized photos

## Interface Overview

The editor has three main panels:

### Left Panel - Filters and Statistics
- **Filter buttons** showing photo counts by status
- **Sort toggle** for filename vs sequence number ordering
- **Current metadata** display for selected photo

### Center Panel - Photo Preview
- Large preview of current photo
- Navigation arrows (← →)
- Photo counter (e.g., "45 of 523")
- Grid view when clicking active filter again

### Right Panel - Metadata Editor
- Quick action buttons (Unknown Date/Location)
- Date entry fields
- Location search with Apple Maps
- Dual location suggestions when available
- Save button and import controls

## Basic Workflow

### 1. Select a Filter

Start with "Needs Review" to see unprocessed photos:

| Filter | Color | Description |
|--------|-------|-------------|
| **Needs Review** | Blue | Photos not yet saved (start here) |
| **Needs Both** | Red | Missing date AND location |
| **Needs Date** | Orange | Has location, needs date |
| **Needs Location** | Orange | Has date, needs location |
| **Complete** | Green | Fully tagged photos |

Click any filter to view those photos. **Click the active filter again to enter grid view**.

### 2. Add Date Information

#### Automatic Suggestions

The tool detects dates and locations in filenames:

| Filename Pattern | Detected Date | Detected Location |
|-----------------|---------------|-------------------|
| `Birthday_Chicago_IL_July_4_1995_0871.heic` | July 4, 1995 | Chicago, IL |
| `Vacation_FL_1995_041.heic` | 1995 | FL |
| `Trip_1995_07_04_1001.heic` | July 4, 1995 | None |

When detected, blue suggestion buttons appear for both date and location.

When you navigate to a photo:
1. You'll might see **"Analyzing..."** buttons while the LLM processes the filename
2. After a moment, the suggestion information will appear
3. The LLM pre-processes upcoming photos so they're ready instantly

**Location will offer two options:**
- **Specific**: More detailed location (e.g., "Hardrock Stadium, Miami Gardens, FL")  
- **General**: Broader location (e.g., "Miami, FL")

#### Manual Entry

Type directly in the date fields:
- **Year**: 4 digits (e.g., 1995)
- **Month**: 1-12 (automatically zero-padded)
- **Day**: 1-31 (automatically zero-padded)

#### Unknown Dates

For photos with no date information:
1. Click **"Unknown Date"** button
2. Sets date to 1901-01-02 (clearly not real)
3. Groups all unknowns together in Apple Photos
4. Click button again to clear and enter a real date

#### Understanding Source Badges

- **Green "User"** - You entered or confirmed this value
- **Orange "System"** - Tool auto-filled this value

System values are replaced when you type.

### 3. Add Location Information

#### Search Types

The unified search box understands:

1. **Cities**: `Chicago` or `Chicago, IL`
2. **States**: `California` or `CA` (uses state capital for GPS)
3. **Landmarks**: `Golden Gate Bridge`, `Statue of Liberty`
4. **Addresses**: `123 Main St, Boston, MA`
5. **Countries**: `France`, `Japan`

#### Using Search

1. Click in the location search box
2. Type at least 2 characters
3. Results appear grouped by category:
   - States
   - Cities  
   - Addresses
   - Places (POIs)
   - Countries
4. Click a result to select
5. GPS coordinates are added automatically

#### Frequent Locations

Your most-used locations appear as quick-select pills:
```
[Chicago, IL (45)] [Disney World (23)] [Grandma's House (12)]
```

Click any pill to instantly apply that location. The number shows how many times you've used it.

#### Unknown Locations

Click **"Unknown Location"** to clear location data and add MissingLocation tag. Click again to re-enable location entry.

### 4. Save Your Work

**⌘S** or click **Save** to:
- Write metadata to the photo file
- Update the database
- Automatically advance to the next photo

Changes are permanent - there is no undo.

## Keyboard Shortcuts

| Key | Action | Context |
|-----|--------|---------|
| **⌘S** | Save current photo | Always available |
| **←** | Previous photo | When not typing |
| **→** | Next photo | When not typing |
| **Tab** | Next field | In date fields |
| **Shift+Tab** | Previous field | In date fields |

## Additional Features

### Grid View

Click any active filter again to see grid view:
- Thumbnails of all photos in that filter
- 50 photos per page with pagination
- Click any thumbnail to jump to that photo
- Checkboxes for selecting multiple photos
- Green ✓ indicator on imported photos

### Batch Selection (Grid View)

1. Enter grid view by clicking active filter
2. Use checkboxes to select multiple photos
3. "Select All" button selects visible photos, Clear removes
4. Selected photos can be sent to Apple Photos as batch
5. All selected photos must be saved first

### Sort Options

Toggle **"Sort by #"** in the left panel to change ordering:

| Sort Mode | Description | Example Order |
|-----------|-------------|---------------|
| **Off** (default) | Alphabetical by filename | `Chicago_1995.heic`, `Denver_1994.heic` |
| **On** | By number at end of filename | `scan_0001.heic`, `scan_0002.heic`, `scan_0010.heic` |

Useful when photos were scanned in chronological order. Non-numeric endings sort to the end.

### Re-sending Photos

For photos already imported to Apple Photos:

1. **Single Photo Mode Only** - Feature disabled in grid view
2. First click shows: **"Already in Photos"**
3. Click again within 3 seconds: **"Click again to re-send"**
4. Third click confirms and re-sends
5. Creates duplicates in Apple Photos - use carefully

### Send to Photos Button States

The button changes based on photo status:

| Button Text | Meaning | Action Required |
|-------------|---------|-----------------|
| **Save First** | Changes not saved | Save before sending |
| **Send to Photos** | Ready to transfer | Click to send |
| **Already in Photos** | Previously imported | Click to enable re-send |
| **Click again to re-send** | Confirm re-send | Click again within 3 seconds |

> **Note**: "Send to Photos" requires [Pipeline Setup](pipeline.md) for Mac-to-Mac transfer.

## Understanding Metadata

### What Gets Saved

When you save, the tool writes:
- **Date/Time**: When the photo was taken
- **GPS Coordinates**: Exact location (if available)
- **City/State**: Human-readable location
- **Camera Info**: Your camera or scanner details (if no camera data exists)
- **Keywords**: Tags to track completion status

### Status Tracking

The tool uses keywords to track photo status:
- **MissingDate**: Photo needs date information
- **MissingLocation**: Photo needs location information

These are removed when you provide the missing information.

**Using Tags in Apple Photos:**
You can search for incomplete photos in Apple Photos by:
1. Open Apple Photos
2. Search for "MissingDate" or "MissingLocation" 
3. These will show all photos still needing that information
4. As you complete photos in the tool, these tags are automatically removed

### Camera Data Preservation

If a photo has real camera metadata:
- Original camera make/model is preserved
- Only date and location are updated
- Look for camera indicator in the current metadata panel

### Status Tracking

The tool uses keywords to track photo status:
- **MissingDate**: Photo needs date information
- **MissingLocation**: Photo needs location information

These are removed when you provide the missing information.

### LLM Parsing Issues

**"Analyzing..." stays too long (>10 seconds)**
- Navigate to another photo and back
- The LLM model might be loading (first and photos only)
- Check if you have enough RAM (Activity Monitor)

**No suggestions appear**
- Filename might not contain recognizable patterns
- Rename file, check if LLM is downloaded and active

**Wrong suggestions**
- The LLM makes educated guesses from limited context
- Simply ignore suggestions and enter manually
- (Advanced) Attempt to update internal prompt

### Performance

**First and Second photo are slow**
- Normal - LLM model takes ~6 seconds to warm up and cache the next 3 images
- Subsequent photos will be much faster
- Model only loads once per session

**High memory usage**
- The LLM model uses ~4GB RAM
- Can disable LLM in settings (see Reference guide)

## Next Steps

- To transfer photos between Macs, see [Pipeline Setup](pipeline.md)
- For technical details, see [Reference](reference.md)
- For troubleshooting, see [Reference](reference.md#troubleshooting)
