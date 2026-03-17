from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ConfigIssue:
    level: str
    key: str
    message: str


@dataclass(slots=True)
class ConfigReport:
    issues: list[ConfigIssue]

    @property
    def errors(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.level == 'ERROR']

    @property
    def warnings(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.level == 'WARN']

    def to_dict(self) -> dict:
        return {
            'errors': [asdict(i) for i in self.errors],
            'warnings': [asdict(i) for i in self.warnings],
            'error_count': len(self.errors),
            'warning_count': len(self.warnings),
        }


def _ensure_bool(cfg: dict[str, Any], key: str, issues: list[ConfigIssue]) -> None:
    if key in cfg and not isinstance(cfg.get(key), bool):
        issues.append(ConfigIssue('ERROR', key, 'Expected a boolean value.'))


def _ensure_int(cfg: dict[str, Any], key: str, issues: list[ConfigIssue]) -> None:
    val = cfg.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        issues.append(ConfigIssue('ERROR', key, 'Expected an integer value.'))


def validate_config_object(cfg: dict[str, Any]) -> ConfigReport:
    issues: list[ConfigIssue] = []
    if not isinstance(cfg, dict):
        return ConfigReport([ConfigIssue('ERROR', 'config', 'Config must be a JSON object.')])

    for key in ('total_members', 'base_attendance', 'budget_total', 'activity_default_days', 'exports_keep_files', 'backups_keep_files'):
        _ensure_int(cfg, key, issues)

    for key in ('default_log_channel_id', 'antispam_notify_channel_id'):
        _ensure_int(cfg, key, issues)

    for key in ('ai_enabled', 'antispam_enabled', 'public_autoresponse_enabled', 'relay_enabled', 'activity_tracking_enabled'):
        _ensure_bool(cfg, key, issues)

    forecast = cfg.get('forecast')
    if not isinstance(forecast, dict):
        issues.append(ConfigIssue('ERROR', 'forecast', 'Missing or invalid forecast section.'))
    elif 'min_attendance' not in forecast:
        issues.append(ConfigIssue('ERROR', 'forecast.min_attendance', 'Missing required forecast setting.'))

    channels = cfg.get('channels')
    if not isinstance(channels, dict):
        issues.append(ConfigIssue('ERROR', 'channels', 'Missing or invalid channels mapping.'))
    else:
        for key in ('announcements', 'rules', 'e-board', 'default-log'):
            if key not in channels:
                issues.append(ConfigIssue('WARN', f'channels.{key}', 'Recommended channel key missing.'))

    if 'private_consult_owner_id' in cfg and not isinstance(cfg.get('private_consult_owner_id'), (int, str)):
        issues.append(ConfigIssue('ERROR', 'private_consult_owner_id', 'Expected a Discord user ID as string or integer.'))

    action = str(cfg.get('antispam_action') or '')
    if action and action not in {'notify', 'timeout'}:
        issues.append(ConfigIssue('WARN', 'antispam_action', 'Recommended values are notify or timeout.'))

    # Public baseline: version is optional and may be blank for initial releases.

    return ConfigReport(issues)


def validate_config_file(path: str | Path) -> ConfigReport:
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    return validate_config_object(cfg)
