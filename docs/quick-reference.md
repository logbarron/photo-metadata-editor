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

## Date Patterns (Auto-Detected)

- `July_4_1995` → July 4, 1995
- `July_1995` → July 1995
- `1995-07-04` → July 4, 1995
- `1995` → 1995 only

## Location Patterns (Auto-Detected)

- `Chicago_IL` → Chicago, IL
- `Denver_CO` → Denver, CO
- `_TX_` → Texas (state only)

## Photo Sorting

- **Default**: Alphabetical by filename
- **Sort by #**: By number at end of filename (_0001, _0002)
- Toggle switch in left panel header

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

- 🟢 **Green "User" badge** - You entered this
- 🟠 **Orange "System" badge** - Tool filled this
- ✅ **Green check** - Already imported to Photos
- 📤 **Send icon** - Ready for import
- 💾 **"Save First" button** - You must save before sending to Photos

## Button States

### Send to Photos Button
- **"💾 Save First"** - Changes not saved yet
- **"📤 Send to Photos"** - Ready to transfer
- **"✅ Already in Photos"** - Previously imported (click to enable re-send)
- **"⚠️ Click again to re-send"** - Confirm creating duplicate (3 second timeout)

## ⚠️ Important

**This tool permanently modifies files!** Always keep backups.

---

For full documentation: See docs folder