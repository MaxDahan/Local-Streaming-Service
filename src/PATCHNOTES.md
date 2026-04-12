# MAXISTREAMS Patch Notes

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
