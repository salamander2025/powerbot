# PowerBot

PowerBot is a plug-and-play Discord assistant for clubs and organizations.

It helps you manage tasks, events, and decisions directly inside Discord using simple commands — with optional local AI (no API key required).

---

## 🚀 Quick Start

1. Install **Python 3**
   - (On Windows, installing from the Microsoft Store is fine)

2. Create a Discord bot (see steps below) and copy its token

3. Enable **Message Content Intent** (required)

4. Set up your `.env` file:
   - Copy `.env.example`
   - Rename the copy to `.env`
   - Open `.env`
   - Paste your token after:
     DISCORD_TOKEN=your_token_here
   - Save the file

5. Invite the bot to your server (steps below)

6. Double-click `start.bat`

---

## 🧩 Create the Discord bot (token)

1. Go to: https://discord.com/developers/applications  
2. Click **New Application** → name it → create  
3. Open **Bot** (left sidebar)  
4. Click **Reset Token** or **Copy**  
5. Save the token (you’ll paste it into `.env`)

---

## ✅ Enable Message Content Intent (required)

1. Go to **Bot** settings in the Developer Portal  
2. Scroll to **Privileged Gateway Intents**  
3. Turn ON **Message Content Intent**  
4. Click **Save Changes**

If you see this error:
PrivilegedIntentsRequired

This setting fixes it.

---

## 🔗 Invite the bot to your server

1. Go to **OAuth2 → URL Generator**  
2. Under **Scopes**, check:
   - bot  
3. Under **Bot Permissions**, check:
   - Send Messages  
   - Read Message History  
4. Copy the generated URL  
5. Open it → select your server → click **Authorize**

---

## 🔑 Setup (.env)

Open `.env` and configure:

Required:
- DISCORD_TOKEN — your bot token

Optional:
- POWERBOT_OWNER_ID — your Discord user ID  
- POWERBOT_OWNER_ROLE_ID — role-based owner access  
- AI_BACKEND — ollama (default) or none  

---

## 🤖 Optional AI setup (Ollama)

1. Install Ollama: https://ollama.com  
2. Run:
   ollama pull llama3.1

If Ollama is not running, the bot still works.

---

## 🧠 Example commands

!help  
!examples  
!pb my tasks  
!pb add task for Treasurer to confirm budget by Friday high priority  
!pb add event welcome night on Sept 10 at Student Center  
!pb dashboard  

---

## 🧭 Project structure

- bot.py — main entry point  
- bot_core.py — main logic  
- powerbot_core/ — internal modules  
- cogs/ — command modules  
- docs/ — documentation  
- data/ — storage  

---

## 👥 Who this is for

- student clubs  
- campus organizations  
- community groups  
- small teams  

---

## 📦 Features

- Task system  
- Event tracking  
- Meeting tools  
- Optional AI  
- Fully self-hosted  
