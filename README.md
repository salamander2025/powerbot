# PowerBot

Manage tasks, events, and decisions in Discord using natural language.

PowerBot is a plug-and-play Discord assistant for clubs and organizations: tasks, events, dashboards, and (optional) local AI.

---

## 🚀 Quick Start

1. Install **Python 3** (on Windows, installing from the Microsoft Store is fine).
2. Create a Discord bot in the **Discord Developer Portal** and copy its **token**.
3. In the Developer Portal, enable **Message Content Intent** (required).
4. Copy `.env.example` and rename the copy to `.env`
5. Open `.env` (it’s a text file)
6. Paste your token after:
   DISCORD_TOKEN=your_token_here
7. Save the file
8. Invite the bot to your server (steps below)
9. Double-click `start.bat`

---

## 🧩 Create the Discord bot (token)

1. Go to the Discord Developer Portal: https://discord.com/developers/applications
2. Click **New Application** → name it → create
3. In the left sidebar, open **Bot**
4. Click **Reset Token** (or **Copy**) and save it somewhere safe

---

## ✅ Enable Message Content Intent (required)

1. In the Developer Portal → your application → **Bot**
2. Scroll to **Privileged Gateway Intents**
3. Turn on **Message Content Intent**
4. Click **Save Changes**

If you see:
PrivilegedIntentsRequired

This setting fixes it.

---

## 🔗 Invite the bot to your server

1. In the Developer Portal → your application → **OAuth2 → URL Generator**
2. Under **Scopes**, check **bot**
3. Under **Bot Permissions**, check:
   - Send Messages
   - Read Message History
4. Copy the generated URL
5. Open it in your browser → select your server → click **Authorize**

---

## 🔑 Setup (.env)

Open `.env` and set:

Required:
- DISCORD_TOKEN — your Discord bot token

Optional (recommended later):
- POWERBOT_OWNER_ID — your Discord user ID for owner-only commands
- POWERBOT_OWNER_ROLE_ID — optional Discord role ID
- AI_BACKEND — ollama (default) or none

---

## 🤖 Optional AI setup (Ollama)

PowerBot can run AI locally (no API key required):

1. Install Ollama: https://ollama.com
2. Run:
   ollama pull llama3.1

If Ollama isn’t running, the bot still works (AI features will be limited).

---

## 🧠 Example commands

- !help
- !examples
- !pb my tasks
- !pb add task for Treasurer to confirm budget by Friday high priority
- !pb add event welcome night on Sept 10 at Student Center
- !pb dashboard

---

## 🧭 Project structure

- bot.py — main entry point
- bot_core.py — main logic and command system
- powerbot_core/ — internal modules
- cogs/ — command modules
- docs/ — documentation
- data/ — local storage

---

## 👥 Who this is for

- student clubs
- campus organizations
- community groups
- small teams

---

## 📦 What this bot includes

- Task system (owners, priorities, due dates, status)
- Event tracking + dashboards
- Meeting utilities (summaries / action-item import)
- Optional local AI backend (Ollama)
- Local data storage under `data/` (config + knowledge + logs)
