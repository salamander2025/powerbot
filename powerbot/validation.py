"""Data validation (Cerberus).

Optional: If Cerberus isn't installed, validation functions return (True, {}).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


CONFIG_SCHEMA = {
    # Core forecasting knobs
    "total_members": {"type": "integer", "min": 1, "required": False},
    "base_attendance": {"type": "integer", "min": 0, "required": False},
    "last_updated": {"type": "string", "required": False},

    # AI switches (safe-by-default)
    "ai_enabled": {"type": "boolean", "required": False},
    "ai_private_active": {"type": "boolean", "required": False},
    "ai_private_session_id": {"nullable": True, "required": False},
    "ai_private_channel_id": {"nullable": True, "required": False},
    "private_consult_active": {"type": "boolean", "required": False},
    "private_consult_session": {"nullable": True, "required": False},
    "private_consult_owner_id": {"nullable": True, "required": False},

    # Digest scheduling
    "weekly_digest_channel_id": {"nullable": True, "required": False},
    "weekly_digest_weekday": {"type": "integer", "min": 0, "max": 6, "required": False},
    "weekly_digest_hour": {"type": "integer", "min": 0, "max": 23, "required": False},

    # Channel routing (IDs stored in config.json)
    "default_log_channel_id": {"nullable": True, "required": False},
    "channels": {"type": "dict", "required": False},
    "bot_channels": {"type": "dict", "required": False},
    "voice_channels": {"type": "dict", "required": False},

    # Anti-spam
    "antispam_enabled": {"type": "boolean", "required": False},
    "antispam_notify_channel_id": {"nullable": True, "required": False},
    "antispam_notify_channel": {"type": "string", "required": False},
    "antispam_exempt_channel_ids": {"type": "list", "required": False},
    "antispam_window_seconds": {"type": "integer", "min": 1, "required": False},
    "antispam_max_msgs_in_window": {"type": "integer", "min": 1, "required": False},
    "antispam_duplicate_threshold": {"type": "integer", "min": 1, "required": False},
    "antispam_links_window_seconds": {"type": "integer", "min": 1, "required": False},
    "antispam_max_links_in_window": {"type": "integer", "min": 1, "required": False},
    "antispam_alert_cooldown_seconds": {"type": "integer", "min": 0, "required": False},
    "antispam_action": {"type": "string", "required": False},
    "antispam_timeout_minutes": {"type": "integer", "min": 1, "required": False},

    # Forecast (nested)
    "forecast": {"type": "dict", "required": False},
    "multipliers": {"type": "dict", "required": False},

    # Budget and retention
    "budget_total": {"type": "integer", "min": 0, "required": False},
    "exports_keep_files": {"type": "integer", "min": 0, "required": False},
    "backups_keep_files": {"type": "integer", "min": 0, "required": False},

    # Relay and activity
    "public_autoresponse_enabled": {"type": "boolean", "required": False},
    "relay_enabled": {"type": "boolean", "required": False},
    "relay_control_guild_id": {"nullable": True, "required": False},
    "relay_control_user_id": {"nullable": True, "required": False},
    "relay_target_guild_id": {"nullable": True, "required": False},
    "relay_target_channel_id": {"nullable": True, "required": False},
    "relay_control_channel_id": {"nullable": True, "required": False},
    "activity_tracking_enabled": {"type": "boolean", "required": False},
    "activity_default_days": {"type": "integer", "min": 1, "required": False},

    # Version and command hub customization
    "version": {"type": "string", "required": False},
    # Command hub customization (public defaults)
    "owner_hints": {"type": "list", "schema": {"type": "string"}, "required": False},
    "known_events": {"type": "list", "schema": {"type": "string"}, "required": False},
}


def validate(schema: Dict[str, Any], doc: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    try:
        from cerberus import Validator  # type: ignore
        # Allow extra keys without spamming warnings. We still validate known keys.
        v = Validator(schema, allow_unknown=True)
        ok = v.validate(doc)
        return ok, dict(v.errors)
    except Exception:
        return True, {}
