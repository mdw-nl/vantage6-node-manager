# 📸 Vantage6 Node Manager - UI Screenshots Guide

This document describes the visual appearance and layout of each page in the application.

## 🏠 Dashboard (`/`)

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│ 🎨 Navigation Bar (Dark Blue)                                │
│ 🔘 Vantage6 Node Manager | Dashboard | Nodes | New Node     │
└─────────────────────────────────────────────────────────────┘
┌──────┬──────────────────────────────────────────────────────┐
│ 📋  │  🎯 DASHBOARD                                          │
│ Side │                                                        │
│ bar  │  ┌───────────┐ ┌───────────┐ ┌───────────┐         │
│      │  │   📊 3    │ │   ✅ 2    │ │   ⏹️ 1    │         │
│ • 📊 │  │Total Nodes│ │  Running  │ │  Stopped  │         │
│ • 📋 │  └───────────┘ └───────────┘ └───────────┘         │
│ • ➕ │                                                        │
│ ---  │  📌 Quick Actions                                     │
│ • 📖 │  [➕ Create New Node] [📋 View All Nodes]            │
│      │                                                        │
│      │  📜 All Configured Nodes                              │
│      │  ┌────────────────────────────────────────────────┐  │
│      │  │ Name        Status    Type    Server   Actions │  │
│      │  ├────────────────────────────────────────────────┤  │
│      │  │ hospital-a  🟢Running user   https://... 👁▶⏹ │  │
│      │  │ clinic-b    🔴Stopped user   https://... 👁▶  │  │
│      │  │ lab-c       🟢Running system https://... 👁▶⏹ │  │
│      │  └────────────────────────────────────────────────┘  │
│      │                                                        │
│      │  🐳 Currently Running Containers                      │
│      │  ┌────────────────────────────────────────────────┐  │
│      │  │ Container Name         ID      Status   Image  │  │
│      │  ├────────────────────────────────────────────────┤  │
│      │  │ vantage6-hospital-a... abc123  running  node:4 │  │
│      │  └────────────────────────────────────────────────┘  │
└──────┴──────────────────────────────────────────────────────┘
```

### Color Scheme
- **Statistics Cards**: Gradient backgrounds (blue, green, red)
- **Running Status**: Green badge with play icon
- **Stopped Status**: Red badge with stop icon
- **Action Buttons**: Info (blue), Success (green), Danger (red)

---

## 📋 All Nodes (`/nodes`)

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│ 🎨 Navigation Bar                                             │
└─────────────────────────────────────────────────────────────┘
┌──────┬──────────────────────────────────────────────────────┐
│ Side │  🗂️ Node Configurations      [➕ Create New Node]    │
│ bar  │                                                        │
│      │  📊 All Configured Nodes (3)                          │
│      │  ┌─────────────────────────────────────────────────┐ │
│      │  │ Name          Status   Type    Server    DB  ... │ │
│      │  ├─────────────────────────────────────────────────┤ │
│      │  │ hospital-a    🟢Run    👤user  https... 1db  👁▶⏹│ │
│      │  │ ~/.config/... (gray text)                       │ │
│      │  ├─────────────────────────────────────────────────┤ │
│      │  │ clinic-b      🔴Stop   👤user  https... 2db  👁▶ │ │
│      │  │ ~/.config/... (gray text)                       │ │
│      │  ├─────────────────────────────────────────────────┤ │
│      │  │ lab-c         🟢Run    ⚙️sys   https... 1db  👁▶⏹│ │
│      │  │ /etc/vantage6/... (gray text)                  │ │
│      │  └─────────────────────────────────────────────────┘ │
└──────┴──────────────────────────────────────────────────────┘
```

### Features
- **Detailed Table**: Shows all node information
- **Status Badges**: Color-coded (green/red/yellow)
- **Type Badges**: User (gray) / System (blue)
- **Action Buttons**: Grouped (View, Start/Stop, Restart)
- **Database Count**: Badge showing number of databases

---

## ➕ Create New Node (`/nodes/new`)

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│ 🎨 Navigation Bar                                             │
└─────────────────────────────────────────────────────────────┘
┌──────┬──────────────────────────────────────────────────────┐
│ Side │  ➕ Create New Node Configuration                      │
│ bar  │                                                        │
│      │  ┌──────────────────┐  ┌─────────────────────────┐   │
│      │  │ 📝 Form          │  │ ℹ️ Help                  │   │
│      │  │                  │  │ Required fields marked  │   │
│      │  │ Basic Info       │  │ with *                  │   │
│      │  │ • Node Name *    │  │                         │   │
│      │  │ [_____________]  │  │ 💡 Example Config       │   │
│      │  │                  │  │ Name: hospital-a        │   │
│      │  │ Server Config    │  │ URL: https://server..   │   │
│      │  │ • Server URL *   │  │ Port: 443               │   │
│      │  │ [_____________]  │  │ DB: /data/patients.csv  │   │
│      │  │ • Port           │  └─────────────────────────┘   │
│      │  │ [_____________]  │                                │
│      │  │ • API Path       │                                │
│      │  │ [/api________]   │                                │
│      │  │                  │                                │
│      │  │ Authentication   │                                │
│      │  │ • API Key *      │                                │
│      │  │ [••••••••••••]   │                                │
│      │  │ Show/Hide        │                                │
│      │  │                  │                                │
│      │  │ Database Config  │                                │
│      │  │ • Label *        │                                │
│      │  │ [default_____]   │                                │
│      │  │ • URI *          │                                │
│      │  │ [/path/to/...]   │                                │
│      │  │ • Type           │                                │
│      │  │ [CSV ▼]          │                                │
│      │  │                  │                                │
│      │  │ Advanced         │                                │
│      │  │ • Task Dir       │                                │
│      │  │ [/tmp/v6_____]   │                                │
│      │  │                  │                                │
│      │  │ [Cancel] [✅Create]│                              │
│      │  └──────────────────┘                                │
└──────┴──────────────────────────────────────────────────────┘
```

### Features
- **Sectioned Form**: Organized by category
- **Help Cards**: Context-sensitive help on right
- **Example Values**: Show best practices
- **Validation**: Client and server-side
- **Toggle Visibility**: For API key field

---

## 👁️ View Node Details (`/nodes/hospital-a`)

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│ 🎨 Navigation Bar                                             │
└─────────────────────────────────────────────────────────────┘
┌──────┬──────────────────────────────────────────────────────┐
│ Side │  🖥️ hospital-a [🟢 Running]    [⬅️ Back to List]     │
│ bar  │                                                        │
│      │  🎛️ Controls                                          │
│      │  [⏹️ Stop] [🔄 Restart] [🔃 Refresh Logs] [🗑️ Delete]│
│      │                                                        │
│      │  ┌──────────────────┐  ┌──────────────────────────┐  │
│      │  │ ℹ️ Configuration │  │ 📦 Container Info        │  │
│      │  │                  │  │ ID: abc123...           │  │
│      │  │ Name: hospital-a │  │ Image: node:4.7.1       │  │
│      │  │ Type: user 🏷️    │  │ Created: 2025-10-19...  │  │
│      │  │ File: ~/.config..│  │ Ports: 8080->8080       │  │
│      │  │ Server: https... │  └──────────────────────────┘  │
│      │  │ Port: 443        │                                │
│      │  │ API: /api        │  ┌──────────────────────────┐  │
│      │  │ Task: /tmp/v6    │  │ 📜 Container Logs        │  │
│      │  │ Encryption: ❌   │  │ [🔃 Refresh]             │  │
│      │  └──────────────────┘  │                          │  │
│      │                         │ ┌──────────────────────┐ │  │
│      │  ┌──────────────────┐  │ │[INFO] Starting...    │ │  │
│      │  │ 💾 Databases     │  │ │[INFO] Connected to...│ │  │
│      │  │                  │  │ │[INFO] Node ready...  │ │  │
│      │  │ Label  Type  URI │  │ │[DEBUG] Waiting...    │ │  │
│      │  │ deflt  csv  /... │  │ │(auto-refresh 5s)     │ │  │
│      │  └──────────────────┘  │ └──────────────────────┘ │  │
│      │                         └──────────────────────────┘  │
└──────┴──────────────────────────────────────────────────────┘
```

### Features
- **Two-Column Layout**: Config on left, runtime info on right
- **Real-Time Logs**: Auto-refresh every 5 seconds
- **Control Panel**: All actions at top
- **Status Badge**: Large, prominent in header
- **Container Details**: When node is running
- **Database Table**: Lists all configured databases

---

## 🎨 Color & Icon Legend

### Status Indicators
- 🟢 **Green** - Running, Success
- 🔴 **Red** - Stopped, Error, Danger
- 🟡 **Yellow** - Warning, Unknown
- 🔵 **Blue** - Info, Primary actions
- ⚪ **Gray** - Secondary, Disabled

### Icons
- 🖥️ Server/Node
- ▶️ Start
- ⏹️ Stop
- 🔄 Restart
- 🔃 Refresh
- 👁️ View
- 🗑️ Delete
- ➕ Create/Add
- ⬅️ Back
- 📊 Dashboard
- 📋 List
- ⚙️ Settings/System
- 👤 User
- 💾 Database
- 📜 Logs
- 📦 Container
- ℹ️ Information
- ✅ Success/Confirm
- ❌ Cancel/Disabled

### Badges
- **Primary (Blue)**: System configurations
- **Secondary (Gray)**: User configurations
- **Info (Light Blue)**: Database count
- **Success (Green)**: Running status
- **Danger (Red)**: Stopped status
- **Warning (Yellow)**: Unknown status

---

## 📱 Responsive Design

### Desktop (>992px)
- Two-column layout (config + runtime)
- Full sidebar visible
- All features accessible

### Tablet (768-992px)
- Stacked columns
- Collapsible sidebar
- Touch-friendly buttons

### Mobile (<768px)
- Single column layout
- Hidden sidebar (hamburger menu)
- Larger touch targets
- Simplified tables

---

## ⚡ Interactive Elements

### Hover Effects
- Buttons: Slight color darkening
- Table rows: Light background highlight
- Links: Underline appears
- Cards: Shadow intensifies

### Click/Tap Feedback
- Buttons: Press animation
- Forms: Focus outline (blue)
- Toggles: Instant visual change

### Auto-Refresh
- Logs: Every 5 seconds
- Status: On navigation
- Dashboard stats: On page load

---

This UI design provides:
- ✅ Clear visual hierarchy
- ✅ Consistent color coding
- ✅ Intuitive navigation
- ✅ Responsive across devices
- ✅ Accessibility considerations
- ✅ Professional appearance
