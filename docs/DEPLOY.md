# Deploy PowerBot 24/7

## Option 1: Local Windows PC
Use `start.bat` and keep the machine online. This is the easiest setup but least reliable.

## Option 2: VPS
Recommended if you want stable 24/7 uptime.
- install Python 3.11+
- clone the repo
- create `.env`
- install requirements
- use `systemd`, `tmux`, or another process manager

## Option 3: Railway / Render / similar
- set environment variables in the host UI
- install from `requirements.txt`
- run `python bot.py`
- make sure the data directory is backed up or persisted

## Backups
Back up at minimum:
- `data/config.json`
- `data/tasks.json`
- `data/events.json`
- `data/knowledge/`

## Before going live
```bash
python tools/check_syntax.py
python tools/validate_config.py
python tools/validate_knowledge.py
```
