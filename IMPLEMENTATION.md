# Model Attribution Bug Fix - Implementation Notes

## Problem
Session `ba5603e0-b395-4ec7-bbd0-187162a5bd17` was incorrectly attributed to `llama3.2:3b` with $42.171 cost, when in reality it contained:
- 353 messages from `claude-sonnet-4-6` costing $42.17
- 4 messages from `llama3.2:3b` costing $0

The bug occurred because the code only captured the model from the **first message** in a session, causing cost misattribution for mixed-model sessions.

## Solution
Modified `parse_session_file()` in `generate_dashboard.py` to track costs per model and attribute the session to the model with the highest total cost.

## Changes Made

### File: `/home/d-tuned/openclaw-usage-dashboard/generate_dashboard.py`

#### Change 1: Added model cost tracking dictionary (Line ~247)
```python
# Added:
model_costs = {}  # Track cost per model for accurate attribution
```

#### Change 2: Replaced first-message model capture with per-model cost tracking (Lines ~295-298)
**Before:**
```python
# Extract provider and model (use first message's values)
if provider is None:
    provider = message.get("provider", "unknown")
if model is None:
    model = message.get("model", "unknown")
```

**After:**
```python
# Extract provider from first message
if provider is None:
    provider = message.get("provider", "unknown")

# Track cost per model for accurate attribution
msg_model = message.get("model", "unknown")
msg_cost = cost_data.get("total", 0.0)
model_costs[msg_model] = model_costs.get(msg_model, 0) + msg_cost
```

#### Change 3: Select highest-cost model before returning SessionData (Lines ~320-325)
**Added before return statement:**
```python
# Attribute session to model with highest total cost
if model_costs:
    model = max(model_costs, key=model_costs.get)
else:
    model = "unknown"
```

## Verification

### Test Command
```bash
grep -A2 "ba5603e0" /home/d-tuned/openclaw-usage-dashboard/dashboard.html | head -5
```

### Result
```
<td>ba5603e0-b395-4ec7-bbd0-187162a5bd17</td>
                <td>interactive</td>
                <td>claude-sonnet-4-6</td>
```

✅ Session now correctly attributed to `claude-sonnet-4-6`

### Dashboard Regeneration
```
2026-03-18 08:20:53,265 - INFO - Starting token usage dashboard generation
2026-03-18 08:20:53,600 - INFO - Parsed 122 sessions
2026-03-18 08:20:53,924 - INFO - Dashboard generated: dashboard.html
2026-03-18 08:20:53,925 - INFO - Processed 122 sessions, 4094 messages
```

## Impact
- All mixed-model sessions now correctly attribute costs to the dominant (highest-cost) model
- Provider attribution unchanged (still uses first message's provider)
- No breaking changes to SessionData structure or dashboard output format
