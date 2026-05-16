# Candilicious

Candilicious is a Discord bot and web platform designed to empower study communities with modern tools, automation, and fun. It combines Discord bot features, a Flask web server, and MongoDB for a seamless study and productivity experience.

---

## Key Features

- **Study Session Management**
  - Configure and monitor study voice channels.
  - Automatic tracking of study time and user activity.
  - Inactivity warnings and auto-disconnect.
  - Exception handling for users with poor network (temporary relief via speedtest).

- **Leaderboards & Progress Tracking**
  - Local and global leaderboards for study time and achievements.
  - Visual project and board progress via the web interface.

- **Fun & Motivation**
  - Meme songs and sound effects in voice channels.
  - Humorous and motivational reminders (GIFs and texts).

- **Web Dashboard**
  - Flask-powered web server for managing projects, boards, and user data.
  - Static pages for Terms, Privacy, About, and more.

- **Cloud & Docker Ready**
  - One-command Docker deployment with health checks and user isolation.
  - Cloud setup and VPN integration scripts for advanced hosting.

- **Data Management**
  - MongoDB backend for users, boards, exceptions, and reminders.
  - Secure token-based access for web features.

---

## Quick Start with Docker

1. **Build & Run:**
   ```bash
   docker run -d --name candilicious --env-file .env -p 10301:10301 wuiiidocker/candilicious:latest
   ```
   Ensure your `.env` file is in the working directory.

2. **Health Check:**
   The container exposes `/ping` for health monitoring.

---

## Manual Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/WuiiiGithub/Candilicious.git
   cd Candilicious
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Set up environment variables:**
   - Create a `.env` file with:
     ```env
     DB_NAME=Candilicious
     TOKEN=YOUR_DISCORD_BOT_TOKEN
     MONGODB_URI=YOUR_MONGODB_CONNECTION_STRING
     FLASK_DOMAIN=http://localhost:10301
     SECRET_KEY=YOUR_SECRET_KEY
     NGROK_AUTH_TOKEN=YOUR_NGROK_TOKEN
     APPLICATION_ID=YOUR_DISCORD_APP_ID
     ```
4. **Run the bot:**
   ```bash
   # Without VPN config OR External VPN
   python3 main.py
   
   # With VPN configuration
   python3 main.py
   ```

---

## Usage

### Discord Commands
- `/config <study_channel>`: Set up study channel.
- `/leaderboard <scope>`: View leaderboards.
- `/exception`: Request network exception.
- `/delete <scope>`: Delete user/server data.
- `/plays <sound>`: Play meme songs.
- `/playeff <sound>`: Play sound effects.
- `/tos`, `/privacy`, `/about`, `/new`: Info and updates.

### Web Endpoints
- `/projects/<token>`: View/manage projects.
- `/boards/<token>/<board_id>`: Board details.
- `/tos`, `/privacy`, `/about`: Static info pages.
- `/ping`: Health check.

---

## Project Structure
- `cogs/`: Discord bot cogs (commands, events: study, reminders, schedules, etc.)
- `library/`: Utilities (logging, session, leaderboard, templates).
- `schemas/`: MongoDB JSON schemas.
- `public/`: Static assets and HTML for Flask.
- `main.py`: Bot and web server entry point.
- `config.py`: Configuration.
- `cloud_setup.py`, `setup_vpn.py`: Cloud/VPN scripts.
- `sendToDB.py`: Data upload utilities.
- `Dockerfile`, `formatDockerMessage.sh`: Containerization scripts.

---

## Contributing

Candilicious is open source and welcomes contributions! You can:
- Submit pull requests for code/features.
- Report bugs or suggest improvements.
- Help test and provide feedback.
- Share with your community.

---

Happy studying with Candilicious! 🎉

---

*Vision: To create a world where students are free in their learning journey, empowered by technology and community.*