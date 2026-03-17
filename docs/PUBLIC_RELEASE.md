# GitHub release checklist

## Goal
Publish a reusable **PowerBot** build without leaking private club history, secrets, IDs, or archives.

## Step 1: Run the privacy scanner
```bash
python tools/check_public_readiness.py --strict
```
Review every warning before publishing.

## Step 2: Review this public repo
Check that it contains:
- no `.env`
- no private archives
- no personal emails
- no live Discord IDs
- generic example knowledge only

## Step 3: Publish to GitHub
Publish this repo only after `.env` is absent, validation passes, and your live club data remains outside the repository.
