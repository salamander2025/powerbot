# PowerBot Architecture

PowerBot is built around a single command hub with structured engines underneath.

## Goal
`!pb <natural language request>` becomes the default public-facing interface.

## Current layers
1. Interface layer
   - `!pb ...`
2. Intent layer
   - rule-based `IntentRouter`
3. Domain engines
   - tracked tasks
   - event status / timeline
   - meeting summaries
   - memory lookup
   - advisor
4. Storage layer
   - `data/tasks.json` (`powerbot.tasks.v2`)
   - existing `events.json`
   - existing knowledge JSON files

## What this release includes
- richer task parsing: owner, due date, priority, event
- task filters like `due this week` and `high priority`
- event status + linked task snapshot
- decisions / action items / unresolved summary sections

## Still intentionally not done
- no hard cutover from legacy commands yet
- no SQLite migration yet
- no Gmail/dashboard layer yet

## Next recommended steps
1. Promote `!pb` to the main user-facing workflow in the live server.
2. Add admin migration helpers from planning notes/chat summaries into tracked tasks.
3. Decide whether tasks/events should move into SQLite for a future release.
4. Only after that: dashboard, email bridge, or more advanced AI layers.
