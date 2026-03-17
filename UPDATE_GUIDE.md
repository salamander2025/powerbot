# Update guide

## Safe update flow
1. Back up these files before replacing code:
   - `data/config.json`
   - `data/tasks.json`
   - `data/events.json`
   - `data/knowledge/`
2. Replace the codebase with the new version.
3. Re-run validation:
```bash
python tools/check_syntax.py
python tools/validate_config.py
python tools/validate_knowledge.py
pytest -q
```
4. Start the bot and test a few `!pb` commands.

## Preparing a public release
Use the new tooling instead of publishing your live deployment directly:
```bash
python tools/check_public_readiness.py --strict
python tools/build_public_starter.py
```
Publish the generated starter pack, not your private runtime folder.
