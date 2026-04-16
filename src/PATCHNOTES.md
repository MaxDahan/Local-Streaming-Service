# MAXISTREAMS Patch Notes

## v2.0.0 - Browse Mode Overhaul, Themes & Blunt Clicker
**Release: April 2026**

### ✨ New Features
- **Blunt Clicker** - Added a 🚬 shared blunt button — authenticated users can hit the blunt and contribute to a global + per-user count
- **Blunt Leaderboard** - Tracks top blunt hitters with per-user counts; only accessible to logged-in users
- **BNZ Media Theme** - New black & white ink-art theme with custom white-outline overlay art
- **Xbox Theme** - New Xbox-green dark theme with neon green accents and Xbox wallpaper overlay
- **Two new theme slots in theme picker** - BNZ Media and Xbox available to all users

### 🖥️ Browse Mode Improvements
- **Browse Dashboard** - Added a visual library dashboard with folder cover art cards when entering Browse mode
- **Recently Played Section** - Dashboard now shows recently played shows with progress bars and season/episode labels (e.g. *Season 2 · Ep 4/13*)
- **Folder Subgrid** - Clicking a show folder now shows its contents as a card grid on the right side
- **Season-aware subfolder navigation** - Clicking a Season folder in the subgrid now loads that season in the left sidebar and shows the folder prompt on the right
- **← Back card** - First card in every subgrid is now a dashed Back card to navigate up to the parent folder
- **Homescreen cleanup** - Navigating home via the MAXISTREAMS logo now properly clears browse library cards and folder prompts

### 🔖 Chronological Resume Improvements
- **Show-level chrono position** - Chronological position and Resume button now always reference the top-level show folder (e.g. *Adventure Time*), even when viewing a Season subfolder — so position reflects the full series, not just the season
- **Recently played auto-resume** - Clicking a card in the Recently Played section now immediately starts Chronological Resume from your saved checkpoint, no extra button click needed
- **Chrono position shows season context** - Resume button and status line now display season + episode within season alongside overall position (e.g. *Season 2: 4/13 (overall: 30/298)*)

### 🐛 Fixes
- **Blunt counter no longer resets on server restart** — `blunt_hits` was being stripped from the user database on every load; now persistently saved and reloaded correctly
- **Blunt count drift prevention** — Server startup now re-syncs the global blunt count from per-user hit totals to prevent any future counter divergence
- **Browse → Home chat missing** — Fixed chat lobby not appearing after navigating from Browse back to the home screen
- **Subgrid folder clicks now sync left sidebar** — Clicking a folder card on the right side now loads that folder's contents in the left sidebar (previously only the Back button did this)
- **Non-media files hidden in Browse** — Only folders and `.mp4` files are shown in the sidebar and subgrid; subtitle files, images, and other media artifacts are hidden
- **Removed 📁 folder emoji** from browse cards that have no cover art
- **Recently played season label** — Was incorrectly showing "Ep 8/298" (full library count); now correctly shows season-scoped episode count

---

## v1.9.0 - Homepage Presence, Admin UX & Data Safety
**Release: April 2026**

### ✨ New Features
- **Homepage Presence Card** - Added a live "Current Users" list on homepage
- **Homepage Lobby Chat** - Added live chat directly on homepage with dedicated lobby channel
- **Per-Channel Chat Visibility Memory** - Chat hide/show now remembers state per channel context

### 🖥️ UI Improvements
- Added "Additional Info" section organization on homepage
- Improved account panel actions layout and login-aware button visibility
- Moved Admin Health access into the account panel for cleaner dock UI
- Updated admin entry styling for clearer visual hierarchy

### 🛠️ Admin & Health Dashboard
- Added **Reload Users** action in admin dashboard
- Added **Delete User** action in admin dashboard (with safeguards)
- Updated logout control label to **Clear Admin Session**
- Added two-step confirmation flow for Clear Admin Session
- Clarified load average display as **1m / 5m / 15m**
- Fixed Process RSS metric reporting (real process RSS instead of placeholder)

### 🔒 Account & Data Handling
- Consolidated account storage to `src/configurations/users.json`
- Removed legacy fallback users DB behavior
- Ensured users data files are git-ignored to avoid accidental commits

### 🐛 Fixes
- Fixed homepage chat not appearing due to stale mount behavior after re-render
- Fixed scroll position reset when switching between homepage/channels/playback
- Fixed guest visibility behavior for online users (login-required messaging)

## v1.8.0 - Accounts, Per-User Resume & Access Controls
**Release: April 2026**

### ✨ New Features
- **Account System** - Added account create/login/logout with persistent sessions and remember-me support
- **Account Management** - Added password change and username rename (with cooldown protection)
- **Per-User Chronological Checkpoints** - Chronological resume now tracks position per account (instead of shared guest state)
- **Checkpoint Preview API** - Added endpoint to preview the exact episode/position chronological resume will play next

### 🖥️ UI Improvements
- Added folder playback prompt with dual modes: `Shuffle Play` and `Chronological Resume`
- Chronological UI now shows:
	- current chronological position (`X/Y`)
	- next episode title (`Next up: ...`)
- Open folder prompt now refreshes checkpoint state immediately after login/logout
- Logging into an already playing channel now immediately enables chat (no channel switch needed)
- Logged-out channel viewers now still see the chat panel with a clear login-required message

### 🔒 Access Control Changes
- **Chat is now account-only**: reading and sending messages requires login
- **Chronological checkpoints are now account-only**: preview + chronological playback require login
- Clear UI guidance is shown when users try to access protected features while logged out

### 🎬 Playback Controls
- Channel/live streams now hide play/pause controls
- On-demand playback controls remain unchanged

### 🐛 Reliability Fixes
- Fixed stale "login required" checkpoint text not refreshing when user logs in while folder prompt is open
- Fixed chat state requiring a channel switch after login before becoming usable

---

## v1.7.1 - Chronological Resume UX Polish
**Release: April 2026**

### 🖥️ UI Improvements
- Reworked chronological button copy for better readability
- Added dedicated chronological status lines under folder play actions
- Improved loading/fallback text for checkpoint position and next-episode preview

### 🐛 Fixes
- Improved resilience when checkpoint preview fails by falling back to clear, non-blocking messaging

## v1.7.0 - Cookie Clicker, Chat Persistence & Polish
**Release: April 2026**

### ✨ New Features
- **Global Cookie Clicker** - Added a shared 🍪 cookie button — every user's click adds to a global counter
- **Cookie Counter Persistence** - Cookie count survives server restarts, saved to disk on every click and on shutdown
- **Chat History Persistence** - Per-channel chat messages are now saved to disk and restored on server startup
- **Patch Notes Redesign** - Patch notes now render left-aligned with clear release headers, category labels, and better typography

### 🖥️ UI Improvements
- Floating panels (theme, username) now pop upward and are mutually exclusive — opening one closes the other
- Fixed invisible hit area next to floating buttons that prevented click-away from closing menus
- Selecting a theme now auto-closes the theme panel
- Saving a username now auto-closes the username panel
- Cookie score label now has a pill background and brighter text for easy readability
- Theme selection panel now correctly appears above the username panel (z-index fix)

### 🐛 Reliability Fixes
- Fixed theme overlay shifting position when switching between Browse, Channels, Home, and Playback modes — overlay is now viewport-fixed and stays locked
- Removed obsolete overlay duplication and dynamic height-sync logic (no longer needed after overlay stabilization)
- Fixed cookie counter resetting to 0 every 4 seconds due to empty POST body being mishandled before the click handler

---

## v1.6.1 - On-Demand Loading UX Upgrade
**Release: April 2026**

### ✨ New Features
- **On-Demand Loading Overlay** - Added a polished loading panel over the skeleton screen while on-demand streams prepare
- **Smooth Progress Bar** - Added a live progress bar with percentage during on-demand startup
- **Segment-Aware Progress** - Loading progress now reflects generated `.ts` segments and elapsed startup time

### 🖥️ UI Improvements
- Added clearer loading status text for file/folder on-demand requests
- Improved retry interaction feedback for individual file loads
- Added theme-aware pressed-state visuals when re-clicking a loading file

### 🐛 Reliability Fixes
- Added on-demand startup timeout handling to prevent infinite loading states
- Added proper failure recovery when on-demand requests fail to start
- Fixed retry flows for individual files so re-click truly restarts loading
- Fixed retry label restoration so file names return correctly after loading
- Fixed an on-demand switch race where selecting a second file right after playback could prevent the new loader/progress from appearing

---

## v1.6.0 - Live Chat & Stream UX Update
**Release: April 2026**

### ✨ New Features
- **Per-Channel Live Chat** - Each channel now has its own live chat under the stream
- **Username Identity** - Added a floating user button to set and save your chat username
- **Chat Timestamps** - Messages now include date and 24-hour time in English format
- **Chat Controls** - Added a `Hide/Show` toggle to quickly collapse chat while watching

### 🖥️ UI Improvements
- Added a dedicated chat panel beneath the current stream view
- Improved chat message layout for readability (timestamp, username, message)
- Enhanced homepage presentation and card styling for a cleaner official look
- Kept theme customization controls accessible while reducing sidebar clutter

### 🐛 Bug Fixes
- Fixed patch notes not refreshing when returning home via the logo button
- Fixed chat input clipping and layout cutoff issues
- Fixed stream/chat positioning conflicts during playback
- Improved theme overlay handling during long homepage scrolling

### ⚙️ Chat Backend
- Added new API endpoints for live chat messaging and polling
- Added per-channel in-memory chat storage with message limits
- Enabled real-time chat updates with periodic client polling

---

## v1.5.0 - Theme System & UI Polish
**Release: April 2026**

### ✨ New Features
- **Multi-Theme System** - Choose from 5+ customizable themes including Pokemon theme
- **Per-Theme Customization** - Each theme can have custom colors, images, and overlays
- **Theme Persistence** - Your theme choice is saved across browser sessions
- **Theme Button UI** - Interactive theme selector with live previews

### 🎨 Themes Added
- Default (Classic dark mode)
- Volcano (Fiery reds and oranges)
- Space (Deep blacks and starlight)
- Dinosaur (Earthy greens and browns)
- Beach (Sandy warm tones)
- Counter-Strike GO (Sleek gaming aesthetic)
- Pokemon (Colorful and playful)

### 🐛 Bug Fixes
- Fixed theme flash on page refresh
- Resolved selection preview persisting after mode switch
- Improved theme button responsiveness
- Fixed theme persistence for manifest-only themes

### ⚡ Performance
- Optimized theme loading and caching
- Reduced CSS paint operations
- Faster image asset loading

---

## v1.4.0 - Enhanced UI & Search
**Release: March 2026**

### ✨ New Features
- Improved search functionality
- Better preview text for selections
- Enhanced status indicators

### 🎨 UI Improvements
- Refined sidebar colors
- Better contrast for readability
- Improved button styling

---

## v1.3.0 - Core Streaming Features
**Release: February 2026**

### ✨ Features
- Channel browsing and filtering
- Random channel playback
- Watchlist management
- HLS.js integration for smooth playback
