# Sort Functionality Documentation

This document comprehensively documents all code areas related to the sort functionality in the photo metadata editor application.

## Overview

The application supports two sorting modes:
1. **Sort by Filename** (default): Alphabetical sorting by filename
2. **Sort by Sequence Number**: Numerical sorting by extracted sequence numbers from filenames

## Python File (`photo_metadata_editor.py`) - Sort Related Code

### 1. State Management

**Location**: `photo_metadata_editor.py:431`
```python
self.sort_by_sequence: bool = False
```
- Global state variable that tracks the current sort mode
- `False` = sort by filename (default)
- `True` = sort by sequence number

### 2. Sequence Number Extraction Function

**Location**: `photo_metadata_editor.py:558-570`
```python
def extract_sequence_number(filename: str) -> Optional[int]:
    """Extracts the trailing number from a filename for sorting."""
    # Remove common extensions
    base = filename.replace('.heic', '').replace('.HEIC', '')
    parts = base.split('_')
    if parts:
        try:
            # The last part is assumed to be the sequence number
            return int(parts[-1])
        except (ValueError, IndexError):
            # No valid number found
            return None
    return None
```
- Extracts sequence numbers from filenames for sorting
- Removes HEIC extensions and splits on underscores
- Takes the last part as the sequence number
- Returns `None` if no valid number is found

### 3. Database Query Sorting Logic

**Location**: `photo_metadata_editor.py:1764-1773`
```python
def get_filtered_photos(self, filter_type: str) -> List[str]:
    """Get photos based on filter, sorted by the database."""
    with self.get_db() as conn:
        # Determine the ORDER BY clause based on the global sort mode
        if STATE.sort_by_sequence:
            # Sort by the pre-calculated sequence number, with filename as a tie-breaker.
            # NULLS LAST ensures photos without a sequence number appear at the end.
            order_by_clause = "ORDER BY sequence_number ASC NULLS LAST, filename ASC"
        else:
            # Default sort by filename
            order_by_clause = "ORDER BY filename ASC"
```
- Main sorting logic for database queries
- **Sequence mode**: `ORDER BY sequence_number ASC NULLS LAST, filename ASC`
  - Primary sort: sequence number ascending
  - Secondary sort: filename ascending (tie-breaker)
  - Photos without sequence numbers appear at the end
- **Filename mode**: `ORDER BY filename ASC`
  - Simple alphabetical sort by filename

### 4. Grid Data Sorting

**Location**: `photo_metadata_editor.py:5138`
```python
# Sort by index to maintain order
grid_data.sort(key=lambda x: x['index'])
```
- Maintains order in grid view based on index
- Used to preserve the database sort order in the UI

### 5. API Endpoint - Toggle Sort

**Location**: `photo_metadata_editor.py:5208-5216`
```python
@app.route('/api/toggle_sort', methods=['POST'])
def toggle_sort():
    """Toggle between filename and sequence number sorting"""
    STATE.sort_by_sequence = not STATE.sort_by_sequence
    STATE.current_index = 0
    return jsonify({
        'success': True,
        'sort_by_sequence': STATE.sort_by_sequence
    })
```
- HTTP endpoint for toggling sort mode
- Flips the `sort_by_sequence` boolean
- Resets current index to 0 (first photo)
- Returns current sort state to frontend

### 6. Initial Photo List Loading

**Location**: `photo_metadata_editor.py:5503-5506`
```python
# Find photos
STATE.photos_list = sorted([
    f for f in STATE.working_dir.iterdir()
    if f.is_file() and f.suffix.lower() == '.heic'
])
```
- Initial loading sorts photos alphabetically by default
- This is the fallback sorting when not using database-based sorting

## HTML File (`photo_editor_ui.html`) - Sort Related Code

### 1. CSS Styling for Sort Toggle

**Location**: `photo_editor_ui.html:820-870`

#### Main Toggle Container
```css
/* Sort Toggle */
.sort-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--text-secondary);
}
```

#### Hidden Checkbox
```css
.sort-toggle input {
    display: none;
}
```

#### Toggle Slider Styles
- **Base state**: `photo_editor_ui.html:855-857`
- **Checked state**: `photo_editor_ui.html:859-861`
- **Label styling**: `photo_editor_ui.html:867-869`

### 2. HTML Toggle Element

**Location**: `photo_editor_ui.html:878-882`
```html
<label class="sort-toggle">
    <input type="checkbox" id="sort-toggle" onchange="toggleSort()">
    <span class="toggle-slider"></span>
    <span class="toggle-label">Sort by #</span>
</label>
```
- Checkbox input with `onchange="toggleSort()"` event handler
- Visual toggle slider component
- Label displays "Sort by #" text

### 3. JavaScript Toggle Function

**Location**: `photo_editor_ui.html:2569-2592`
```javascript
// Toggle sort mode
async function toggleSort() {
    try {
        const response = await fetch('/api/toggle_sort', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (response.ok) {
            const result = await response.json();
            // Reload current view with new sort order
            if (gridMode) {
                // If in grid mode, refresh grid
                await showGridView(currentGridFilter, 0);
            } else {
                // Reset to first photo with new sort
                STATE.current_index = 0;
                await loadCurrentPhoto();
            }
        }
    } catch (error) {
        console.error('Error toggling sort:', error);
    }
}
```
- Calls the `/api/toggle_sort` endpoint
- Refreshes the current view after sort change:
  - **Grid mode**: Calls `showGridView()` with current filter
  - **Single photo mode**: Resets to first photo and calls `loadCurrentPhoto()`
- Includes error handling for failed requests

## Sort Functionality Flow

1. **User clicks toggle** → `toggleSort()` JavaScript function
2. **Frontend calls API** → `POST /api/toggle_sort`
3. **Backend toggles state** → `STATE.sort_by_sequence = not STATE.sort_by_sequence`
4. **Frontend refreshes view** → Either `showGridView()` or `loadCurrentPhoto()`
5. **New database queries** → Use updated `order_by_clause` based on sort mode
6. **Photos displayed in new order** → According to chosen sort mode

## Key Variables and States

- `STATE.sort_by_sequence` (Python): Boolean controlling sort mode
- `sort-toggle` (HTML): Checkbox element ID
- `toggleSort()` (JavaScript): Function name for toggle action
- `sequence_number` (Database): Field used for sequence-based sorting
- `filename` (Database): Field used for filename-based sorting

## Additional Critical Dependencies

### Database Schema and Migration

**Location**: `photo_metadata_editor.py:1390, 1568-1583, 1600`
- **Table column**: `sequence_number INTEGER` in photos table
- **Migration logic**: Adds column if doesn't exist and populates existing photos
- **Database index**: `CREATE INDEX IF NOT EXISTS idx_photos_sequence ON photos(sequence_number)`

### Photo Processing Integration

**Location**: `photo_metadata_editor.py:5694, 5756`
```python
'sequence_number': extract_sequence_number(photo.name),
```
- Every photo insert/update calculates and stores sequence_number
- Used in database UPSERT operations

### Index Reset Points (STATE.current_index = 0)

Sort changes trigger index resets in multiple places:
- **Toggle sort**: `photo_metadata_editor.py:5212`
- **Filter changes**: `photo_metadata_editor.py:5158` 
- **Index bounds checking**: `photo_metadata_editor.py:4462`

### Frontend Integration Points

**JavaScript STATE.current_index references**:
- **Grid mode refresh**: `photo_editor_ui.html:2583` - `await showGridView(currentGridFilter, 0)`
- **Single photo refresh**: `photo_editor_ui.html:2585-2586` - `STATE.current_index = 0; await loadCurrentPhoto()`

## Database Implications

The sort functionality relies on:
- **sequence_number field**: Pre-calculated during photo processing using `extract_sequence_number()`
- **NULLS LAST**: Ensures photos without sequence numbers appear at the end when sorting by sequence
- **filename field**: Fallback and tie-breaker for sorting
- **Database index**: Optimized queries with `idx_photos_sequence` index

## Summary: Complete Code Coverage

**Python References (4 locations)**:
1. `STATE.sort_by_sequence` declaration (:431)
2. `extract_sequence_number()` function (:558-570)
3. Database query logic (:1767-1773)
4. `/api/toggle_sort` endpoint (:5208-5216)

**HTML/JavaScript References (3 locations)**:
1. CSS styling (`.sort-toggle` :820-870)
2. HTML element (`id="sort-toggle"` :879)
3. JavaScript function (`toggleSort()` :2570-2592)

**Database References (6 locations)**:
1. Schema definition (:1390)
2. Migration logic (:1568-1583)
3. Index creation (:1600)
4. Photo processing (:5694)
5. UPSERT operations (:5756)
6. Query ORDER BY clause (:1770, 1773)

**All index reset dependencies are accounted for and would need updating if sort behavior changes.**

---

## IMPORTANT FINDINGS: Sort Direction & Available Fields

### Sort Direction Analysis
**CRITICAL**: There is **NO existing sort direction (ASC/DESC) functionality**. 

Current implementation:
- **All sorting is ASC (ascending) only**
- **No arrow buttons or direction toggles exist**
- **No DESC (descending) sorting capability**

The screenshots showing arrows/direction must be for **NEW functionality to implement**.

### Complete Database Fields Available for Sorting

Based on comprehensive schema analysis, here are **ALL available fields** in the `photos` table:

#### **File & Basic Info**
- `filepath` (TEXT PRIMARY KEY)
- `filename` (TEXT) - **currently used**
- `sequence_number` (INTEGER) - **currently used**
- `file_hash` (TEXT)
- `file_last_modified` (TIMESTAMP) - **ideal for "Date Created"**

#### **Original Metadata (from file scan)**
- `original_scan_time` (TIMESTAMP) - when first scanned
- `original_date_year` (TEXT)
- `original_date_month` (TEXT) 
- `original_date_day` (TEXT)
- `original_date_source` (TEXT) - 'exif', 'filename', 'none'
- `original_gps_lat` (REAL)
- `original_gps_lon` (REAL)
- `original_city` (TEXT)
- `original_state` (TEXT)
- `original_location_source` (TEXT) - 'gps', 'iptc', 'filename', 'none'
- `original_camera_make` (TEXT)
- `original_camera_model` (TEXT)

#### **Current State (editable)**
- `current_date_year` (TEXT)
- `current_date_month` (TEXT)
- `current_date_day` (TEXT) 
- `current_date_source` (TEXT)
- `current_gps_lat` (REAL)
- `current_gps_lon` (REAL)
- `current_city` (TEXT)
- `current_state` (TEXT)
- `current_location_source` (TEXT)
- `current_country` (TEXT)
- `current_country_code` (TEXT)
- `current_street` (TEXT)
- `current_postal_code` (TEXT)
- `current_neighborhood` (TEXT)

#### **User Actions & Status**
- `user_action` (TEXT) - 'saved', 'skipped', 'none'
- `user_last_action_time` (TIMESTAMP)
- `needs_date` (BOOLEAN)
- `needs_location` (BOOLEAN)
- `ready_for_review` (BOOLEAN)

#### **Quality Flags**
- `has_good_date` (BOOLEAN)
- `has_good_gps` (BOOLEAN) 
- `has_good_location` (BOOLEAN)

#### **Import Pipeline**
- `import_batch_id` (TEXT)
- `import_status` (TEXT)
- `imported_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

#### **Additional Metadata**
- `date_from_complete_suggestion` (BOOLEAN)
- `location_gps_source` (TEXT)
- `location_landmark_name` (TEXT)
- `has_camera_metadata` (BOOLEAN)
- `original_make` (TEXT)
- `original_model` (TEXT)
- `last_saved_at` (TIMESTAMP)

#### **LLM Suggestions**
- `suggested_date_year` (TEXT)
- `suggested_date_month` (TEXT)
- `suggested_date_day` (TEXT)
- `suggested_date_complete` (BOOLEAN)
- `suggested_location_primary` (TEXT)
- `suggested_location_alternate` (TEXT)
- `suggested_location_city` (TEXT)
- `suggested_location_state` (TEXT)
- `suggested_location_confidence` (INTEGER)
- `suggested_location_type` (TEXT)
- `suggested_location_reasoning` (TEXT)
- `suggested_location_landmark` (TEXT)
- `suggestion_parsed_at` (TIMESTAMP)
- `suggestion_filename` (TEXT)

#### **System Fields**
- `deleted_at` (TIMESTAMP)
- `created_at` (TEXT)
- `last_modified` (TEXT)

### Recommended Sort Options for Dropdown

Based on the screenshots and available fields:

1. **By Filename** (current) - `ORDER BY filename ASC/DESC`
2. **By Sequence** (current) - `ORDER BY sequence_number ASC/DESC NULLS LAST, filename ASC/DESC`  
3. **By Date Created** (new) - `ORDER BY file_last_modified ASC/DESC`
4. **By Date Modified** - `ORDER BY updated_at ASC/DESC`
5. **By Last Saved** - `ORDER BY last_saved_at ASC/DESC NULLS LAST`
6. **By Photo Date** - `ORDER BY original_date_year ASC/DESC, original_date_month ASC/DESC, original_date_day ASC/DESC`
7. **By Import Date** - `ORDER BY imported_at ASC/DESC NULLS LAST`
8. **By Camera Make/Model** - `ORDER BY original_camera_make ASC/DESC, original_camera_model ASC/DESC`

### Implementation Requirements

To implement the dropdown with direction arrows:

1. **Replace boolean `sort_by_sequence`** with:
   - `sort_field` (string): field to sort by
   - `sort_direction` (string): 'ASC' or 'DESC'

2. **Update all 13 code locations** identified in this documentation

3. **Add direction toggle arrows** in UI next to dropdown

4. **Update database queries** to handle multiple fields and directions

---

## COMPLETE IMPACT ANALYSIS: All Code Areas Requiring Changes

### Target Implementation
**Dropdown with 5 options + Direction arrows:**
1. By Filename
2. By Sequence 
3. By Photo Date (`original_date_year/month/day`)
4. By Date Created (`file_last_modified`)
5. By Date Modified (`updated_at`)

### State Management Changes Required

**REPLACE:**
```python
self.sort_by_sequence: bool = False  # Line 431
```

**WITH:**
```python
self.sort_field: str = "filename"     # filename, sequence, photo_date, date_created, date_modified
self.sort_direction: str = "ASC"      # ASC or DESC
```

### All Code Locations Requiring Updates

#### Python File Changes (10 locations)

**1. State Declaration** - `photo_metadata_editor.py:431`
- Replace `sort_by_sequence: bool = False`
- Add `sort_field: str = "filename"` and `sort_direction: str = "ASC"`

**2. Database Query Logic** - `photo_metadata_editor.py:1767-1773`
- Replace entire if/else block with switch logic for 5 sort options
- Handle complex photo date sorting (year/month/day fields)
- Add DESC capability to all queries

**3. API Endpoint** - `photo_metadata_editor.py:5208-5216`
- Replace `/api/toggle_sort` with `/api/set_sort`
- Change from POST toggle to POST with `field` and `direction` parameters
- Update return JSON structure

**4. Grid Data Sorting** - `photo_metadata_editor.py:5138`
- Verify this preserves new database sort order

**5. Index Reset Points** (4 locations need verification):
- Line 4462: `STATE.current_index = 0` (bounds checking)
- Line 5158: `STATE.current_index = 0` (filter changes)  
- Line 5212: `STATE.current_index = 0` (sort changes)
- Line 5076: Navigation bounds checking

**6. Photo Processing** - `photo_metadata_editor.py:5694`
- Verify `extract_sequence_number()` still used for sequence sorting

**7. Database Schema** - Already has required fields:
- `original_date_year/month/day` ✓
- `file_last_modified` ✓ 
- `updated_at` ✓

#### HTML File Changes (7 locations)

**8. CSS Styles** - `photo_editor_ui.html:821-869`
- Replace `.sort-toggle` styles with dropdown + arrow button styles
- Remove toggle slider CSS (9 style rules)
- Add dropdown container, select element, and arrow button styles

**9. HTML Element** - `photo_editor_ui.html:878-882`
- Replace entire `<label class="sort-toggle">` block
- Add dropdown `<select>` with 5 options
- Add up/down arrow buttons

**10. JavaScript Function** - `photo_editor_ui.html:2570-2592`
- Replace `toggleSort()` with `setSortField()` and `setSortDirection()`
- Update API call to send field + direction
- Handle dropdown change events and arrow button clicks

### New Database Query Logic Required

**Photo Date Sorting** (most complex):
```sql
ORDER BY 
  CASE WHEN original_date_year IS NULL THEN 1 ELSE 0 END,
  CAST(original_date_year AS INTEGER) {ASC/DESC},
  CAST(original_date_month AS INTEGER) {ASC/DESC}, 
  CAST(original_date_day AS INTEGER) {ASC/DESC},
  filename {ASC/DESC}
```

**Other Sort Queries:**
- Filename: `ORDER BY filename {ASC/DESC}`
- Sequence: `ORDER BY sequence_number {ASC/DESC} NULLS LAST, filename {ASC/DESC}`
- Date Created: `ORDER BY file_last_modified {ASC/DESC}`
- Date Modified: `ORDER BY updated_at {ASC/DESC} NULLS LAST`

### API Changes Required

**Current:**
```
POST /api/toggle_sort
Response: {"success": true, "sort_by_sequence": false}
```

**New:**
```
POST /api/set_sort  
Body: {"field": "photo_date", "direction": "DESC"}
Response: {"success": true, "sort_field": "photo_date", "sort_direction": "DESC"}
```

### Frontend State Management

**Add JavaScript variables:**
```javascript
let currentSortField = "filename";
let currentSortDirection = "ASC";
```

### Index Reset Verification Needed

All 4 index reset locations must be tested to ensure they work with:
- Complex photo date sorting with NULL handling
- All 5 sort field options  
- Both ASC/DESC directions

### Total: 17 Code Locations Requiring Changes
- **Python**: 10 locations (state, queries, API, processing)
- **HTML/CSS/JS**: 7 locations (styles, elements, functions)

### Critical Implementation Notes

1. **Photo Date complexity**: Requires special NULL handling and multi-field sorting
2. **Backwards compatibility**: Consider migration path for existing `sort_by_sequence` state
3. **Performance**: May need database index on `updated_at` for Date Modified sorting
4. **Error handling**: All sort fields must handle NULL values appropriately
5. **UI state sync**: Dropdown and arrows must stay synchronized