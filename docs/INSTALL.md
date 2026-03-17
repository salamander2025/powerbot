# Install PowerBot

This guide is written for beginners. You do **not** need to create a virtual environment or run pip commands manually — `start.bat` handles it.

## Quick install (recommended)

1. Install **Python 3**.
2. Create a Discord bot in the Developer Portal, copy its token, and enable **Message Content Intent** (required).
3. Make a copy of `.env.example` and rename the copy to `.env`
4. Open `.env` and paste your token after `DISCORD_TOKEN=`
5. Save the file
6. Invite the bot to your server
7. Double-click `start.bat`

If you see `PrivilegedIntentsRequired`, go back to the Developer Portal and enable **Message Content Intent** for your bot.

## Advanced / manual install (optional)

Use this only if you prefer running commands yourself.

### Requirements
- Python 3.11+
- A Discord bot token

### Create a virtual environment

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

### Install dependencies

```bash
python -m pip install -r requirements.txt
```

### Prepare environment variables

Copy `.env.example` to `.env` and set at least `DISCORD_TOKEN`.

### Start the bot

```bash
python bot.py
```
