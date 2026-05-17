# Candilicious
Candilicious is a powerful, integrated Discord bot and web platform designed to foster high-productivity study environments. It combines automated study session tracking, a real-time web dashboard for task management, and motivational tools to keep communities focused.
<center>
<img src="./public/assets/favicon/android-chrome-192x192.png" width=256 height=256 />
<img src="./public/assets/candiliciousBoard.webp" width=256 height=256 />
</center>

---

## 🌟 Key Features

### ⏱️ Automated Study Tracking
- **Voice Channel Monitoring:** Automatically tracks study time for users in designated voice channels.
- **Activity Verification:** Ensures productivity by requiring users to have their **camera on** or **screen share** active.
- **Inactivity Protection:** Automatically warns and disconnects users who stop their activity for more than 5 minutes.
- **Network Exceptions:** Users with poor internet connections can request a 10-minute exception by performing an automated network speed test via a secure web link.

### 💰 Rewards & Gamification
- **Gold Drops:** Randomly rewards active learners in the study channel with virtual gold coins to keep the atmosphere engaging (upcomming).
- **Leaderboards:** Local rankings to encourage friendly competition within the server (upcoming with styles).

### 📋 Integrated Task Management
- **Dynamic Project Access:** When a user joins a study VC, they are DM'd a unique, temporary **Project Access Link** (and QR code).
- **Web-Based Boards:** Manage "Projects" and "Boards" with a Kanban-like task interface (Todo, Cooking, Done) directly in the browser.
- **Session-Locked Security:** Dashboard access is only valid while the user is actively in the study voice channel.

### 🔔 Motivational Reminders
- **Customizable Reminders:** Server admins can configure periodic reminders with humorous "emotional damage" style GIFs and motivational texts.
- **Personal Timers:** Users can set their own reminders for study breaks or tasks.

---

## 🛠️ Support Files
The repository includes several utility scripts to assist with deployment and data management:
- `config.py`: Centralized configuration for database names, ports, and study session thresholds.
- `sendToDB.py`: An administrative utility to populate the MongoDB database with initial content (TOS, Privacy Policy, motivational GIFs/Texts).
- `cloud_setup.py`: A simple helper script for cloning or pulling the latest repository updates on a server.
- `setup_vpn.py`: Provides functions to connect or disconnect from ProtonVPN for secure hosting environments.

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.8+
- MongoDB instance (Local or Atlas)
- Discord Bot Token & Application ID
- Ngrok Auth Token (for public web access)

### Manual Installation
1. **Clone the repository:**
   ```bash
   git clone https://github.com/WuiiiGithub/Candilicious.git
   cd Candilicious
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Environment:**
   Create a `.env` file in the root directory:
   ```env
   TOKEN=your_discord_bot_token
   APPLICATION_ID=your_discord_app_id
   MONGODB_URI=your_mongodb_uri
   DB_NAME=Candilicious
   FLASK_APP_PORT=10301
   FLASK_DOMAIN=http://your-domain-or-ip:10301
   SECRET_KEY=your_random_secret_key
   NGROK_AUTH_TOKEN=your_ngrok_token
   ```
4. **Initialize Database:**
   Run the utility script to upload necessary data:
   ```bash
   python3 sendToDB.py
   ```
5. **Launch the Application:**
   5.1. *Without inherent VPN support*
   ```bash
   python3 main.py
   ```
   5.2. *With Proton VPN support*
   ```bash
   python3 main.py vpn
   ```

**Tip:** 
If you want to use vpn, but facing issues in `5.2.`, then, connect normally to vpn and then use `5.1.` approach of this section.

---

## ⌨️ Command Reference

### Study & Productivity
- `/config <channel> <interval> <drop>`: Set the study voice channel and reward parameters.
- `/exception`: Request a network exception if you cannot share video/screen.
- `/leaderboard <view> <scope>`: View local study rankings by name or display name.
- `/delete <scope>`: Permanently delete your user data or the server's configuration.
- `/remainder <days> <hrs> <mins> <secs> <text>`: Set a personal timer that DMs you when it expires.

### General & Info
- `/site`: Get the link to the web dashboard.
- `/ping`: Check the bot's latency.
- `/tos`, `/privacy`, `/about`, `/new`: View legal documents and the latest update notes.
- `/invite`: Generate a server invite link.

### Administration (Context Menus)
- **Add GIF to Reminders:** (Right-click message) Adds a GIF from a message to the bot's reminder pool.
- **Add Text to Reminders:** (Right-click message) Adds the message text to the bot's reminder pool.

### Under Construction 🏗️
The following commands are currently being developed:
- `/balance`: Check your earned gold coins.
- `/attendence`, `/clean`, `/lookup`, `/doubt`, `/find`, `/competitive`.

---

## 🌐 Web Interface
The built-in Flask server provides:
- **Project Dashboard:** `/projects/<token>` - Visual overview of your active projects.
- **Task Boards:** `/boards/<token>/<board_id>` - Detailed task management for specific boards.
- **Network Test:** `/except/<token>` - Automated speed test for study exceptions.
- **Health Check:** `/ping` - Returns 'OK' if the database and server are responsive.

---

## 🐳 Docker Deployment
You can run Candilicious in a containerized environment:
```bash
docker build -t candilicious .
docker run -d --name candilicious --env-file .env -p 10301:10301 candilicious
```
In run, if facing some port based issues try this instead:
```bash
docker run -d --name candilicious --dns 8.8.8.8 --env-file .env -p 10301:10301 wuiiidocker/candilicious:latest
```

---

## 🤝 Contributing
Candilicious is open source and driven by a powerful [Vision](./VISION.md) for educational reform. If you'd like to help us build a world where students are free in their learning journey, please check out our [Contribution Guidelines](./CONTRIBUTING.md).

---

> ***Happy studying with Candilicious! 🎉***