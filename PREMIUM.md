# Candilicious — Premium Specification

> **Document type:** Product & implementation spec
> **Status:** Design proposal — pending approval
> **Scope:** Defines exactly what becomes premium, the two `/subscribe` subscriptions, free-mode pricing for one-time unlocks, subscriber discounts, what becomes free, and the implementable style/design system.
> **Related code:** `cogs/premium.py`, `config.py` (`PREMIUM_*`), `routes/workspace.py` (`PremiumData`), `cogs/study.py` (`/leaderboard`, `/holiday`, `/boostxp`), `cogs/community.py` (`/find`), `library/leaderboard.py`, frontend `app/(pages)/*`, `app/components/*`.

---

## 1. Executive Summary

Candilicious stays **free at its core** (per our [Vision](VISION.md) — learning tools must remain accessible). Premium exists to:

1. Let power users unlock convenience, capacity, and cosmetics.
2. Turn the in-app currency **Iron 🔧** into a real, spendable premium currency.
3. Give dedicated studiers **two optional subscriptions** that bundle unlocks cheaper than buying them one-by-one.

**The deal in one line:** *Free earns Wood & Iron. Iron buys one-time unlocks. Subscriptions bundle them — making paid features free and dropping the price of the rest.*

| Mode | What you get | What it costs |
|---|---|---|
| **Free** | 100% of study tracking, kanban, notes, socials, drops | Nothing (forever) |
| **Free + Iron** | Buy cosmetic/utility unlocks one-time with Iron 🔧 | Iron (earned by studying) |
| **Pro** | The core premium bundle + 50% off one-time unlocks | **100 Iron / 7 days** |
| **Elite** | Everything Pro + rare cosmetics + boosts + free unlocks | **250 Iron / 7 days** |

---

## 2. The Currency Model

Two resources already exist in the economy. Premium only assigns them clear roles.

| Currency | Emoji | Earning rate (defaults) | Degrades | Role |
|---|---|---|---|---|
| **Wood** | 🪵 | High (mean ≈ 60 per drop, decays with VC level) | 5%/day | Utility & gameplay (level-ups, holidays) |
| **Iron** | 🔧 | Low (mean ≈ 20, only on 3–15% of drops based on activity tier) | 3%/day | **Premium currency** — subscriptions + one-time unlocks |

Config defaults (`config.py:77-79`, editable in admin → Workspace → Premium): `cost = 100`, `ttl_days = 7`, `unit = "iron"`.

> **Design note:** Iron is scarce by design (~2–4 Iron per hour of active Cam+Stream study), so 100 Iron is a meaningful but achievable weekly cost for an active studier. Prices below assume these defaults.

---

## 3. The Two Subscriptions (`/subscribe`)

The `/subscribe` command (`cogs/premium.py:119`) will present **exactly two subscription options** (plus offer-code redemption via the `code:` argument). Both are **time-limited grants**, stored as `premium.type` on the user document (existing pattern `premium.py:72-83`).

| | 👑 **Pro** | 💎 **Elite** |
|---|---|---|
| **Type key** | `"pro"` | `"elite"` |
| **Price** | 100 Iron 🔧 | 250 Iron 🔧 |
| **Duration** | 7 days | 7 days |
| **Positioning** | The essential premium bundle | Pro + rare cosmetics + max boosts |
| **Renewal** | Manual (re-run `/subscribe`) | Manual |
| **Offer codes** | `premium.offers` codes can grant either type | `premium.offers` codes can grant either type |

### What Pro includes

| Category | Pro perk |
|---|---|
| Leaderboard | **Image leaderboard with Gold border** (replaces text-only; already gated at `study.py:836-872`) |
| Capacity | 15 projects · 15 boards/project · 200 tasks/board (free = 3/3/30) |
| Reminders | 3 active personal reminders, up to 8h each (free = 1, up to 2h) |
| Notes | 5× storage quota + full markdown/LaTeX (same engine) |
| Drops | **+25% drop value** (Wood & Iron) for the session |
| Holiday | **100 Wood/day** (free = 150) |
| Find Buddy | **12 Iron** (free = 25) |
| Cosmetics | 50% off all one-time Iron unlocks; **1 board theme free to apply** |
| Status | 👑 Pro badge on profile + leaderboard |
| Support | Priority queue in the support server |

### What Elite adds (everything in Pro, plus)

| Category | Elite perk |
|---|---|
| Leaderboard | Any border style (**Gold / Silver / Bronze / Wood**, see `library/leaderboard.py`) |
| Capacity | **Unlimited** projects/boards/tasks; 10 active reminders |
| Boost XP | **+100% boost XP** (`/boostxp`, `sessions.py boostxp_session`) |
| Notes | 10× quota + **export to PDF/Markdown** |
| Holiday | **75 Wood/day** |
| Find Buddy | **FREE** |
| Cosmetics | Apply any owned/unlocked cosmetic free while active; permanent purchases 75% off |
| Status | 💎 Elite badge + **gradient name** on leaderboard |
| Sound | All session sound packs unlocked (`TICK/START/COMPLETE` in `boards/session.tsx:94-115`) |
| Early access | Beta features + sneak-peek voting |

### Subscription UI spec (`/subscribe`)

```
┌──────────────────────────────────────────────────────────┐
│  👑 Pro — 100 Iron 🔧 / 7 days                           │
│  Image leaderboards · bigger limits · +25% drops ·       │
│  50% off cosmetics · Pro badge                           │
│  [ Pay 100 Iron ]                                        │
├──────────────────────────────────────────────────────────┤
│  💎 Elite — 250 Iron 🔧 / 7 days                         │
│  Everything in Pro · all LB borders · double XP ·        │
│  free cosmetics · gradient name · early access           │
│  [ Pay 250 Iron ]                                        │
├──────────────────────────────────────────────────────────┤
│  🎁 Have an offer code?        [ Redeem ]                │
└──────────────────────────────────────────────────────────┘
```

---

## 4. What Stays FREE (non-negotiable)

These must never be paywalled — they are the heart of the product and the Vision:

- ✅ Voice study tracking, auto study-VC creation, activity tiers (Cam/Stream)
- ✅ Inactivity warnings & kicks, network `/exception`
- ✅ `/config`, `/vcset`, `/join`, `/leaderboard` (text view, top 10)
- ✅ Wood & Iron drops, `/balance`, degradation system
- ✅ Level-up / `/boostxp` (base XP rate — the **multiplier** is premium, not the mechanic)
- ✅ Projects, Boards, Tasks kanban **at free limits** (3/3/30)
- ✅ Notes explorer at free quota
- ✅ Reminders at free limit (1 active)
- ✅ Profiles, bio, PFP, followers, views
- ✅ Posts (default + custom markdown)
- ✅ `/holiday`, `/streak`, `/pause_dms`, `/find` (at full Iron price)
- ✅ `/tos`, `/privacy`, `/about`, `/help`, `/ping`, `/site`

> **Rule:** We monetize *capacity above free limits, cosmetics, convenience, and multipliers* — never the core study loop.

---

## 5. Free Mode — One-Time Iron Unlocks

In **Free mode**, premium features are available as **one-time permanent purchases** in Iron. This is the "how much to pay to get it" model.

| # | Feature (cosmetic / utility) | One-time price (Iron 🔧) | Free with sub? | Pro buy discount | Elite buy discount |
|---|---|---|---|---|---|
| 1 | Image leaderboard — **Gold** (permanent) | 400 | Pro+ | 200 | 100 |
| 2 | Image leaderboard — **Silver** border | 150 | Pro+ | 75 | 40 |
| 3 | Image leaderboard — **Bronze** border | 165 | Elite | 85 | 40 |
| 4 | Image leaderboard — **Wood** border | 180 | Elite | 90 | 45 |
| 5 | Profile theme (paint your profile card) | 35 | Pro+ | 18 | 9 |
| 6 | Avatar frame (ring around PFP on site) | 25 | Pro+ | 13 | 7 |
| 7 | Board theme (column/card palette) | 30 | Pro+ | 15 | 8 |
| 8 | Custom tick/start/complete sound pack | 10 each | Elite | 5 | 3 |
| 9 | Nickname color on text leaderboard | 15 | Pro+ | 8 | 4 |
| 10 | Pinned project slot (max 3) | 20 | Pro+ | 10 | 5 |

> **Clarifying the model**
> - **Free mode:** buy permanently with Iron. You own it forever (it does not expire).
> - **While subscribed (Pro/Elite):** items marked *"Free with sub?"* are usable **without paying** — the unlock is granted for the subscription duration. Buying them permanently is optional.
> - **After the sub ends:** cosmetics you didn't buy permanently are locked again; anything you did buy stays.

---

## 6. Subscription Effects — What Becomes FREE & Which Payments Drop

This is the explicit "what changes when I subscribe" summary.

### 6.1 Becomes fully FREE (no Iron spent)

| Feature | Free price | Pro | Elite |
|---|---|---|---|
| Image leaderboard (any unlocked border) | 400–180 Iron | ✅ free (Gold) | ✅ free (all) |
| Profile theme | 35 | ✅ free | ✅ free |
| Avatar frame | 25 | ✅ free | ✅ free |
| Board theme (1) | 30 | ✅ free (1) | ✅ free (all) |
| Sound packs | 10 ea | ❌ | ✅ free |
| Nickname color | 15 | ✅ free | ✅ free |
| Pinned project slot | 20 | ✅ free | ✅ free |
| **Find Buddy** | 25 Iron | ❌ (50% off → 12) | ✅ **free** |
| Extra project/board/task capacity | n/a | ✅ free | ✅ free |
| Extra reminders | n/a | ✅ free | ✅ free |

### 6.2 Payments that become LOWER (not free, discounted)

| Feature | Free price | Pro | Elite |
|---|---|---|---|
| Permanent cosmetic purchases | 100% | **50% off** | **75% off** |
| Holiday (paid days) | 150 Wood/day | 100 Wood/day (−33%) | 75 Wood/day (−50%) |
| Find Buddy | 25 Iron | 12 Iron (−50%) | 0 (free) |
| Level-up wood share (group payment) | 100 × level | 80 × level (−20%) | 60 × level (−40%) |

### 6.3 Multipliers & capacity (subscription-only, not purchasable)

| | Free | Pro | Elite |
|---|---|---|---|
| Drop value multiplier | ×1.0 | ×1.25 | ×1.25 |
| Boost XP multiplier (`/boostxp`) | ×1.0 | ×1.0 | ×2.0 |
| Projects | 3 | 15 | ∞ |
| Boards / project | 3 | 15 | ∞ |
| Tasks / board | 30 | 200 | ∞ |
| Active personal reminders | 1 | 3 | 10 |
| Personal reminder max duration | 2h | 8h | 24h |
| Notes quota | 100% | 500% | 1000% + export |

---

## 7. Feature Access Matrix (Full)

| Feature | Free | Free+Iron | Pro | Elite |
|---|---|---|---|---|
| Study tracking (VC, activity, kicks) | ✅ | ✅ | ✅ | ✅ |
| `/exception` network grace | ✅ | ✅ | ✅ | ✅ |
| Wood & Iron drops | ✅ | ✅ | ✅ (×1.25) | ✅ (×1.25) |
| Text leaderboard (top 10) | ✅ | ✅ | ✅ | ✅ |
| Image leaderboard (Gold) | — | 400 🔧 | ✅ | ✅ |
| Image leaderboard (Silver/Bronze/Wood) | — | 150–180 🔧 | Gold only | ✅ |
| `/boostxp` base XP | ✅ | ✅ | ✅ | ✅ (×2) |
| Level-up & wood payment | ✅ | ✅ | −20% | −40% |
| Projects / Boards / Tasks | 3 / 3 / 30 | — | 15 / 15 / 200 | ∞ |
| Board / task drag-drop, priority, rename | ✅ | ✅ | ✅ | ✅ |
| Notes (markdown + LaTeX) | quota | — | ×5 | ×10 + export |
| Personal reminders | 1 × 2h | — | 3 × 8h | 10 × 24h |
| Server reminders (admin) | ✅ | ✅ | ✅ | ✅ |
| `/find` study buddy | 25 🔧 | — | 12 🔧 | free |
| `/holiday` | 150 Wood/day | — | 100 Wood/day | 75 Wood/day |
| Profile / bio / PFP / followers | ✅ | ✅ | ✅ | ✅ |
| Posts (default + custom markdown) | ✅ | ✅ | ✅ | ✅ |
| Profile theme / avatar frame / board theme | — | 25–35 🔧 | free | free |
| Sound packs | 2 default | 10 🔧 ea | 2 default | all |
| Nickname color / pinned project | — | 15–20 🔧 | free | free |
| Badges | — | — | 👑 | 💎 + gradient |
| Early access / priority support | — | — | priority | ✅ |

---

## 8. Implementation Plan

### 8.1 Data model (backend)

Extend the existing `premium` collection pattern (`premium.py:12-21, 72-83`):

```python
# user document  (users collection)
"premium": {
    "type": "pro" | "elite",          # two allowed values
    "purchased_at": <datetime utc>,
    "expire_at": <datetime utc>,      # TTL index on premium.expire_at
}

# owned one-time unlocks  (users collection)
"unlocks": {
    "lb_border_gold": True, "lb_border_silver": True,
    "profile_theme": "id", "avatar_frame": "id",
    "board_theme": ["id"], "sound_pack": ["id"],
    "nickname_color": "#hex", "pinned_projects": ["project_id"],
}
```

- Add `PremiumData` fields in `routes/workspace.py:57-60` for the second tier:
  `cost_elite: float = 250`, `ttl_days_elite: float = 7`.
- Allow `premium.offers` codes to carry `type: "pro" | "elite"` + `days`.

### 8.2 Enforcement points (what to gate & where)

| Gate | Where |
|---|---|
| `is_pro / is_elite` helper (check `premium.type` + `expire_at > now`) | new `library/premium.py` |
| Image leaderboard | `cogs/study.py:836-872` (already gated on `pro`) |
| Leaderboard border style choice | pass `border_style` into `getNovaLeaderboard` (`study.py:864`, `library/leaderboard.py:172`) |
| Capacity limits (projects/boards/tasks) | `routes/projects.py`, `routes/tasks.py` (count + reject) |
| Notes quota | `routes/notes.py` |
| Reminder limits | `cogs/reminders.py` (active task count + max duration) |
| Drop multiplier | `routes/drops.py:33-44` (`calculate_reward`) |
| Boost XP multiplier | `cogs/study.py boostxp` + `routes/sessions.py boostxp_session` |
| Holiday discount | `cogs/study.py` (`HOLIDAY_COST_PER_DAY` → tier-aware) |
| Find-buddy discount | `cogs/community.py` (`FIND_COST`) |
| Cosmetic free-apply / discounts | frontend feature-flag hook + `routes/users.py` unlock endpoints |
| Gradient name / badges | `library/leaderboard.py` renderer + profile page |

### 8.3 Frontend

- New `usePremium()` hook (`lib/useAuth.ts` pattern): reads `premium.type` + expiry from the auth/user payload; exposes `isPro`, `isElite`, `owns('unlock')`, `buyPrice(item)`, `freeDuringSub(item)`.
- Paywall microcopy component (keeps UX honest): “Locked — unlock for 35 Iron 🔧 or get it free with Pro.”
- `/subscribe` page section mirroring the UI spec in §3.

### 8.4 Migration & rollout order

1. **Phase 0:** ship `library/premium.py` helper + `/subscribe` two-tier menu (re-enable `premium.py:119`).
2. **Phase 1:** activate the already-coded premium leaderboard + cosmetic unlocks + discounts (cheap wins).
3. **Phase 2:** capacity limits + note/reminder quotas (needs a grandfathering notice).
4. **Phase 3:** multipliers (drops, boost) + Elite early access.
5. Always keep §4 free list untouched.

---

## 9. Style & Design Spec (implementable)

Premium must be *visible* but tasteful — pink candy palette, consistent with `globals.css` tokens.

### 9.1 Leaderboard borders (`library/leaderboard.py`)

Reuse the existing `add_premium_border(img, style, padding)` generator. Map tiers:

| Style key | Visual | Access |
|---|---|---|
| `gold` | warm gradient frame, pale highlight | Pro+ (default premium) |
| `silver` | cool metallic frame | unlock/Elite |
| `bronze` | dark-to-amber frame | unlock/Elite |
| `wood` | hand-drawn grain, random wood-grain lines | unlock/Elite |

Implementation is 90% present (`leaderboard.py:74-170`) — expose style selection per user tier.

### 9.2 Badges

| Badge | Spec |
|---|---|
| 👑 Pro | 16px crown, `text-amber-400`, next to display name on profile + leaderboard row |
| 💎 Elite | 16px gem, `text-sky-400`; name rendered with `bg-gradient-to-r from-amber-300 via-pink-400 to-sky-400 bg-clip-text text-transparent` (gradient name) |

### 9.3 Cosmetic system (design tokens)

All cosmetics are thin CSS layer swaps — no new frameworks.

| Cosmetic | Implementable spec |
|---|---|
| **Profile theme** | CSS variable set `--profile-bg`, `--profile-accent`, `--profile-card`, applied on `profile/page.tsx` root container |
| **Avatar frame** | wrapper `<div class="rounded-full p-[3px] bg-gradient-to-tr {frame}">` around the avatar `<img>` |
| **Board theme** | per-board column palette override via inline CSS vars in `boards/page.tsx` (`--col-todo`, `--col-cooking`, `--col-done`) |
| **Sound packs** | extend `TICK_SOUNDS/START_SOUNDS/COMPLETE_SOUNDS` arrays (`boards/session.tsx:94-115`); unlock flag filters list |
| **Nickname color** | leaderboard text fill from `unlocks.nickname_color` |

### 9.4 Paywall copy (tone)

Short, sweet, never guilt-trippy:

- *“Unlock for 35 Iron 🔧 — or get it free with Pro.”*
- *“Elite only — this one’s for the 🐐s.”*
- *“Locked. Keep studying, you’re almost there.”*

---

## 10. Pricing Reference (single source of truth)

| Item | Free | Pro | Elite |
|---|---|---|---|
| Pro subscription (7d) | — | **100 🔧** | — |
| Elite subscription (7d) | — | — | **250 🔧** |
| Image LB (Gold) | 400 🔧 | 200 🔧 | 100 🔧 |
| Image LB (Silver/Bronze/Wood) | 150–180 🔧 | 75–90 🔧 | 40–45 🔧 |
| Profile theme | 35 🔧 | 18 🔧 | 9 🔧 |
| Avatar frame | 25 🔧 | 13 🔧 | 7 🔧 |
| Board theme | 30 🔧 | 15 🔧 | 8 🔧 |
| Sound pack | 10 🔧 | 5 🔧 | 3 🔧 |
| Nickname color | 15 🔧 | 8 🔧 | 4 🔧 |
| Pinned project slot | 20 🔧 | 10 🔧 | 5 🔧 |
| Find Buddy | 25 🔧 | 12 🔧 | free |
| Holiday (paid day) | 150 🪵 | 100 🪵 | 75 🪵 |
| Level-up wood share | 100×lvl 🪵 | 80×lvl 🪵 | 60×lvl 🪵 |

> All numbers are **recommended defaults**. Every price is tunable via the admin Workspace → Premium panel (and per-server config document), so the values above can be rebalanced without code changes.

---

*"Premium makes the candy shinier — the cake is still free."* 🍬
