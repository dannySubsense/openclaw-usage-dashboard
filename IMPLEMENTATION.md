# Sortable Columns Implementation for Top Sessions Table

## Summary
Added clickable, sortable column headers to the Top Sessions table in the OpenClaw Usage Dashboard.

## Changes Made

### 1. Modified Row Generation (Line ~507)
**File:** `generate_dashboard.py`

Added data attributes to each table row for sorting:
- `data-timestamp` - Unix timestamp for date sorting
- `data-cost` - Numeric cost value
- `data-tokens` - Total token count
- `data-session` - Session ID string
- `data-model` - Model name string
- `data-type` - Session type string

Example row output:
```html
<tr data-timestamp="1773115800.645" data-cost="42.171" data-tokens="5164066" 
    data-session="ba5603e0-b395-4ec7-bbd0-187162a5bd17" 
    data-model="claude-sonnet-4-6" data-type="interactive">
```

### 2. Updated Table Headers (Line ~930)
Made all column headers clickable with `onclick` handlers and sort indicators:
- Timestamp → `sortTable('timestamp')`
- Session ID → `sortTable('session')`
- Type → `sortTable('type')`
- Model → `sortTable('model')`
- Cost → `sortTable('cost')`
- Tokens → `sortTable('tokens')`

Each header includes a `<span class="sort-indicator">` for the ▲/▼ arrows.

### 3. Added CSS Styling (Line ~730)
Added styles for sortable headers:
```css
.sort-indicator {
    margin-left: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
}

th.sort-asc .sort-indicator::after {
    content: "▲";
    color: var(--color-interactive);
}

th.sort-desc .sort-indicator::after {
    content: "▼";
    color: var(--color-interactive);
}
```

Also enhanced `th:hover` with slightly stronger background color for better feedback.

### 4. Implemented JavaScript Sorting (Line ~1080)
Replaced the placeholder sorting code with a full implementation:

```javascript
function sortTable(column) {
    // Toggle sort direction on repeated clicks
    // Update visual indicators (▲/▼)
    // Sort rows based on data attributes
    // Re-append rows in sorted order
}
```

Features:
- **Toggle sort order**: Clicking the same column reverses the sort direction
- **Visual feedback**: Active column shows ▲ (ascending) or ▼ (descending)
- **Multiple data types**: Handles numbers (timestamp, cost, tokens) and strings (session, model, type)
- **Case-insensitive**: String sorting is case-insensitive

## Testing

1. Generated dashboard: `python3 generate_dashboard.py`
2. Verified HTML output contains:
   - Data attributes on all `<tr>` elements
   - Clickable `<th>` headers with onclick handlers
   - CSS for sort indicators
   - Full JavaScript sorting function

## Sortable Columns

| Column | Data Type | Sort Behavior |
|--------|-----------|---------------|
| Timestamp | Numeric (Unix timestamp) | Chronological |
| Session ID | String | Alphabetical |
| Type | String | Alphabetical |
| Model | String | Alphabetical |
| Cost | Numeric (USD) | Numerical |
| Tokens | Numeric (count) | Numerical |

## Usage

1. Open `dashboard.html` in a browser
2. Click any column header to sort by that column
3. Click the same header again to reverse the sort order
4. Visual indicators (▲/▼) show the current sort column and direction
