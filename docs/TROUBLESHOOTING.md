# Troubleshooting

## Bot does not start
- verify `.env` exists locally
- verify the Discord token is valid
- run `python tools/check_syntax.py`

## Config validation fails
Run:
```bash
python tools/validate_config.py
```
Then fix the missing or invalid keys in `data/config.json`.

## Knowledge validation fails
Run:
```bash
python tools/validate_knowledge.py
```
Then fix the reported JSON files.

## Publishing safely
Run:
```bash
python tools/check_public_readiness.py --strict
```
This helps catch runtime logs, archives, emails, or club-specific details before publishing.
