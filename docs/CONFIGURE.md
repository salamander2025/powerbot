# Configure PowerBot for your club

## Environment variables (.env)
Copy `.env.example` to `.env` and set at least `DISCORD_TOKEN`. Optional:
- `POWERBOT_OWNER_ID` — Discord user ID for the bot owner (defaults to built-in if unset). Use `0` in public builds until you set your own.
- `POWERBOT_OWNER_ROLE_ID` — optional Discord role ID that can run owner-only commands (guild only). Use `0` to disable.
- `POWERBOT_VP_ROLE_ID` — Discord role ID for VP/restricted commands (optional; use `0` to disable).
- `AI_BACKEND` — set to `ollama` (default) or `none` to disable AI.
- `OLLAMA_HOST` — Ollama base URL (default `http://localhost:11434`).
- `AI_MODEL` — Ollama model name (default `llama3.1`).

## Main runtime files
- `data/config.json` — runtime settings, channel IDs, anti-spam, and forecast settings
- `data/tasks.json` — tracked task storage
- `data/events.json` — structured event history
- `data/knowledge/club_memory.json` — your club identity and core facts
- `data/knowledge/qa_rules.json` — quick rule-based answers
- `data/knowledge/planning_notes.json` — meeting notes and planning memory
- `data/knowledge/schedules.json` — structured schedules for members
- `data/knowledge/tone.json` — optional response style tuning

## Recommended configuration flow
1. Fill in `data/config.json`
2. Add your club identity to `club_memory.json`
3. Add a few starter Q&A rules to `qa_rules.json`
4. Add one or two planning-note entries
5. Run:
```bash
python tools/validate_config.py
python tools/validate_knowledge.py
```

## Command hub customization
In `data/config.json` you can optionally set:
- `owner_hints` — list of names used to detect task owners from natural language (e.g. `["President", "Treasurer"]`).
- `known_events` — list of event names for quick matching (e.g. `["welcome-week", "general-meeting"]`).
If omitted, the bot uses built-in defaults. The public starter uses generic role/event names.

## Hub-first usage examples
- `!pb my tasks`
- `!pb add task for Treasurer to confirm budget by Friday high priority`
- `!pb add event welcome night on Sept 10 at Student Center`
- `!pb what still needs to be done for welcome night`
- `!pb summarize the last eboard discussion`
