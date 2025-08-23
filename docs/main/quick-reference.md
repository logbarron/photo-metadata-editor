# Photo Metadata Editor - Quick Reference

## Keyboard Shortcuts

### Navigation
- `←` / `→` - Previous/Next photo (when not typing)
- `Tab` - Next field
- `Shift+Tab` - Previous field

### Actions  
- `⌘S` - Save

## Location Search Examples

| Type | Example | Result |
|------|---------|--------|
| State | `CA` or `California` | California (Sacramento) |
| City | `Chicago` | Chicago, IL |
| Full | `Portland, OR` | Portland, Oregon |
| Landmark | `Golden Gate Bridge` | Exact GPS location |
| Address | `123 Main St, Boston` | Specific address |
| Country | `France` | Country location |

## Filename Patterns (Auto-Detected)

**Recommended Format**: `Description_City_ST_Month_Day_Year_Sequence.heic`

### Date Patterns
- `Beach_Trip_July_4_1995_0041.heic` → July 4, 1995
- `Vacation_July_1995_0701.heic` → July 1995
- `Old_Photos_1995_0054.heic` → 1995 only

### Location Patterns
- `Beach_Trip_Miami_FL_July_4_1995_0084.heic` → Miami, FL
- `Vacation_Chicago_IL_7896.heic` → Chicago, IL
- `Road_Trip_CA_0001.heic` → CA (state only)

**Note**: Sequence numbers (_0001) are required for proper sorting and detection.

## Photo Search

- Search box in left panel searches entire library
- Minimum 2 characters to search
- Searches: filenames, dates, locations, suggestions
- Shows results from ALL filters (not just current)
- Clear with X button to return to filter view

## Photo Sorting

- **Filename**: Alphabetical by filename (default)
- **Sequence #**: By number at end of filename (_0001, _0002)
- **Photo Date**: By when photo was taken
- **Date Created**: By file creation date  
- **Date Modified**: By file modification date
- Toggle ↑↓ button changes sort direction

## Special Buttons

- **Unknown Date** - Sets date to 1901-01-02 (groups unknowns in Photos app), adds MissingDate tag
- **Unknown Location** - Clears location data, adds MissingLocation tag

## Metadata Tags

The tool uses keyword tags to track photo status:

- **MissingDate** - Photo needs date information
  - Applied when: No date, year only, or "unknown" (1901)
  - Removed when: Year AND month are present
  
- **MissingLocation** - Photo needs location information  
  - Applied when: No GPS coordinates AND no city/state
  - Removed when: Has GPS OR has both city and state

These tags are:
- Written to the photo file as Keywords
- Visible in Apple Photos (Keywords field)
- Automatically managed by the tool
- Used by the filters (Needs Date, Needs Location)

## Status Indicators

- **Green "User" badge** - You entered this
- **Orange "System" badge** - Tool filled this
- **Green index badge** (search only) - Photo has complete metadata

## Button States

### Send to Photos Button
- **"Save First"** - Changes not saved yet
- **"Send to Photos"** - Ready to transfer
- **"Already in Photos"** - Previously imported (click to enable re-send)
- **"Click again to re-send"** - Confirm creating duplicate (3 second timeout)

## Important

**This tool permanently modifies files!** Always keep backups.

---

For full documentation: See docs folder
