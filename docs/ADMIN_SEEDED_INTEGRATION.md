# Admin Dashboard Seeded Data Integration

## Overview
Add visibility and control of seeded (demo) data in the admin dashboard.

## Features to Add

### 1. **Filter Toggle** (top of dashboard)
```
[ ] Show seeded data (test/demo data)  [Apply]
```
- Query param: `?show_seeded=on`
- Default: hide seeded data (show real stats only)

### 2. **Stats Breakdown** (in each stat card)
```
Agents
  125         ← real agents
  +50 seeded  ← if seeded exists and filter is on
```

### 3. **Visual Banner** (when viewing seeded data)
```
⚠️ Viewing data with seeded entries included (50 agents, 1000 tasks)
```

### 4. **Cleanup Button** (bottom of dashboard)
```
🗑️ Clean Up Seeded Data
This will remove all demo/test data marked as seeded.
Real agent activity will be preserved.
[Delete 50 agents and 1000 tasks]
```
- Requires confirmation dialog
- Shows count before deleting
- Uses CSRF token

## Implementation

### Query Changes
```python
# Current: counts everything
agent_count = select(func.count()).select_from(Agent)

# New: separate real vs seeded
agent_count_real = ...where(Agent.seeded == False)
agent_count_seed = ...where(Agent.seeded == True)

# Display based on filter
if show_seeded:
    agent_count = agent_count_real + agent_count_seed
else:
    agent_count = agent_count_real
```

### HTML Additions
- Filter form (GET /admin with show_seeded param)
- Stats with seeded breakdown (.sub class)
- Banner (.seeded-banner CSS)
- Cleanup form (POST /admin/cleanup-seeded)

### New Endpoint
```python
@router.post("/admin/cleanup-seeded")
async def admin_cleanup_seeded(...):
    # Same as scripts/seed_marketplace.py --clean
    # But returns to dashboard with success message
```

## Benefits
1. **Transparency**: Always know what's real vs demo
2. **Testing**: Can toggle seeded data on/off easily
3. **Cleanup**: One-click removal when done testing
4. **Analytics**: Real stats aren't polluted by seed data

## Files Modified
- `pinchwork/api/admin_dashboard.py` (queries + HTML + cleanup endpoint)
- `pinchwork/api/admin_styles.py` (CSS for filter-box, seeded-banner, .sub)

## Migration
None required - uses the `seeded` column from migration 006.

---

**Estimated complexity:** Medium (100-150 lines of changes)
**Testing:** Manual (load dashboard, toggle filter, click cleanup)

Should I implement this? 🦞
