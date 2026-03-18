# Dashboard Validation Report

**Generated:** 2026-03-18  
**Dashboard URL:** http://ml-research:8888/dashboard.html  
**Source Directory:** `/home/d-tuned/openclaw-usage-dashboard/`

---

## Check 1: Rendering — **FAIL**

**Status:** No browser available to verify visual rendering

**Notes:**
- Browser tool unavailable (no Chrome/Brave/Edge/Chromium found)
- Canvas tool unavailable (node required)
- Visual rendering could not be verified
- Recommendation: Manually check http://ml-research:8888/dashboard.html in a browser

---

## Check 2: Escaped Tags — **PASS**

**Command:** `grep -c "<\\\\" /home/d-tuned/openclaw-usage-dashboard/dashboard.html`

**Result:** `0` (exit code 1, meaning no matches found)

**Conclusion:** No escaped tags detected in the HTML source.

---

## Check 3: Moonshot Balance — **PASS**

**Expected:** ~$82-83 USD  
**Actual:** `$82.95`

**Source:**
```html
<div class="card-label">Moonshot Balance (Remaining)</div>
<div class="card-value">$82.95</div>
```

**Conclusion:** Moonshot balance displays correctly within expected range.

---

## Check 4: Ollama Cost Bug — **FAIL**

**Issue:** Session `ba5603e0-b395-4ec7-bbd0-187162a5bd17` shows `$42.171` in dashboard but displays model as `llama3.2:3b` (local Ollama model that should cost $0).

**Root Cause Analysis:**

The session contains **1,739 messages** with the following model distribution:

| Model | Message Count | Cost |
|-------|---------------|------|
| `unknown` | 929 | $0 |
| `kimi-k2.5` | 450 | $0 |
| `claude-sonnet-4-6` | 353 | **$42.17** |
| `llama3.2:3b` | 4 | $0 |
| `claude-opus-4-5` | 2 | $0 |
| `gateway-injected` | 1 | $0 |

**The Bug:** The dashboard uses the **first message's model** to label the entire session. In this session, the first message with cost data has `model=llama3.2:3b`, but the actual cost ($42.17) comes from 353 `claude-sonnet-4-6` messages later in the session.

**Location in Code:** `generate_dashboard.py`, `parse_session_file()` function:
```python
if model is None:
    model = message.get("model", "unknown")  # Only captures first model
```

---

## Check 5: Date Range — **PASS**

**Expected:** 2026-02-26 through 2026-03-10  
**Actual Dates Found:**

```
2026-02-24
2026-02-26 ✓
2026-02-27 ✓
2026-02-28 ✓
2026-03-01 ✓
2026-03-02 ✓
2026-03-03 ✓
2026-03-04 ✓
2026-03-05 ✓
2026-03-06 ✓
2026-03-07 ✓
2026-03-08 ✓
2026-03-09 ✓
2026-03-10 ✓
2026-03-11
2026-03-17
2026-03-18
```

**Conclusion:** All expected dates (2026-02-26 through 2026-03-10) are present. Additional dates outside this range also exist.

---

## Check 6: Top Sessions Table — **PASS**

**Structure Verified:** Table exists with correct columns

**Source:**
```html
<section id="top-sessions">
    <h2>Top Sessions by Cost</h2>
    <table id="sessions-table">
        <thead>
            <tr>
                <th data-sort="timestamp">Timestamp</th>
                <th data-sort="session_id">Session ID</th>
                <th data-sort="type">Type</th>
                <th data-sort="model">Model</th>
                <th data-sort="cost">Cost</th>
                <th data-sort="tokens">Tokens</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>2026-03-10 04:10</td>
                <td>ba5603e0-b395-4ec7-bbd0-187162a5bd17</td>
                <td>interactive</td>
                <td>llama3.2:3b</td>
                <td>$42.171</td>
                <td>5,164,066</td>
            </tr>
            ...
        </tbody>
    </table>
</section>
```

**Notes:** Table renders with proper structure and data. The model column shows the (incorrect) session-level model attribution.

---

## Summary

| Check | Status | Notes |
|-------|--------|-------|
| Rendering | ❌ FAIL | Browser unavailable for visual verification |
| Escaped Tags | ✅ PASS | No escaped tags found |
| Moonshot Balance | ✅ PASS | $82.95 (within expected range) |
| Ollama Cost Bug | ❌ FAIL | Session mislabeled - cost from Claude, not Ollama |
| Date Range | ✅ PASS | All expected dates present |
| Top Sessions Table | ✅ PASS | Structure correct, data populated |

**Score:** 4/6 PASS (67%)

---

## Recommended Fixes (Prioritized)

### 🔴 HIGH: Fix Model Attribution Bug
**Issue:** Sessions with mixed models show incorrect model in dashboard  
**Fix:** Track the model that incurred the highest cost per session, not just the first model

**In `generate_dashboard.py`, modify `parse_session_file()`:**
```python
# Instead of:
if model is None:
    model = message.get("model", "unknown")

# Track cost per model and pick the highest:
model_costs = {}
...
msg_model = message.get("model", "unknown")
model_costs[msg_model] = model_costs.get(msg_model, 0) + cost_data.get("total", 0)
...
# At end:
model = max(model_costs.items(), key=lambda x: x[1])[0] if model_costs else "unknown"
```

### 🟡 MEDIUM: Add Visual Rendering Verification
**Issue:** Cannot automatically verify dashboard renders correctly  
**Fix:** Install headless Chrome/Chromium on ml-research for automated screenshot testing

### 🟢 LOW: Add Session Model Breakdown
**Enhancement:** Show all models used in a session with their individual costs in a tooltip or expandable row

---

*Report generated by dashboard validator subagent*
