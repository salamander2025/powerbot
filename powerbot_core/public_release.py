from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SENSITIVE_FILE_PATTERNS = [
    'organization_data.json',
    'data/powerbot_errors.log',
    'data/knowledge/private_eboard_dm_archive.json',
    'data/knowledge/club_info_snippets_archive.json',
    'data/knowledge/ai_private_consultation.json',
]

SENSITIVE_TERM_PATTERNS = {
    'custom_private_term': [],
    'discord_id': [r'\b\d{17,20}\b'],
    'email': [r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'],
}

TEXT_EXTENSIONS = {'.py', '.json', '.md', '.txt', '.yaml', '.yml', '.ini', '.cfg', '.bat'}
WHITELIST_TOP_LEVEL_FILES = [
    'bot.py', 'bot_core.py', 'README.md', 'CHANGELOG.md', 'VERSION',
    'requirements.txt', 'requirements_all.txt', 'requirements_analytics.txt', 'requirements_semantic.txt',
    '.env.example', '.gitignore', 'start.bat', 'Procfile', 'ARCHITECTURE.md', 'UPDATE_GUIDE.md',
]
WHITELIST_DIRS = ['cogs', 'powerbot', 'powerbot_core', 'tools', 'docs']


@dataclass(slots=True)
class ScanFinding:
    level: str
    kind: str
    path: str
    message: str


@dataclass(slots=True)
class ScanReport:
    findings: list[ScanFinding]

    @property
    def errors(self) -> list[ScanFinding]:
        return [f for f in self.findings if f.level == 'ERROR']

    @property
    def warnings(self) -> list[ScanFinding]:
        return [f for f in self.findings if f.level == 'WARN']

    def to_dict(self) -> dict:
        return {
            'errors': [asdict(f) for f in self.errors],
            'warnings': [asdict(f) for f in self.warnings],
            'all_findings': [asdict(f) for f in self.findings],
            'error_count': len(self.errors),
            'warning_count': len(self.warnings),
        }


@dataclass(slots=True)
class BuildSummary:
    output_root: str
    files_written: int
    starter_name: str

    def to_dict(self) -> dict:
        return asdict(self)


def iter_text_files(project_root: Path) -> Iterable[Path]:
    for path in project_root.rglob('*'):
        if not path.is_file():
            continue
        if path.name.startswith('.') and path.name != '.env.example':
            continue
        if any(part in {'__pycache__', '.pytest_cache', '.git', '.venv', 'venv'} for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_EXTENSIONS or path.name.endswith('.example'):
            yield path


def scan_public_readiness(project_root: str | Path) -> ScanReport:
    root = Path(project_root).resolve()
    findings: list[ScanFinding] = []

    for rel in SENSITIVE_FILE_PATTERNS:
        if (root / rel).exists():
            findings.append(ScanFinding(
                level='WARN',
                kind='sensitive_file',
                path=rel,
                message='Potentially private runtime or archive file present; exclude or sanitize before publishing.',
            ))

    if (root / '.env').exists():
        findings.append(ScanFinding(
            level='ERROR',
            kind='secret_file',
            path='.env',
            message='A real .env file exists. Do not publish it; keep only .env.example.',
        ))

    compiled = {kind: [re.compile(pat, re.IGNORECASE) for pat in pats] for kind, pats in SENSITIVE_TERM_PATTERNS.items()}
    for path in iter_text_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for kind, patterns in compiled.items():
            count = sum(len(pattern.findall(text)) for pattern in patterns)
            if not count:
                continue
            if kind == 'custom_private_term' and rel in {'powerbot_core/public_release.py', 'tools/dry_run.py', 'tools/run_regression_tests.py', 'tools/validate_knowledge.py', 'data/knowledge/compiled_rules.json'}:
                continue
            level = 'ERROR' if kind == 'email' and rel != '.env.example' else 'WARN'
            findings.append(ScanFinding(
                level=level,
                kind=kind,
                path=rel,
                message=f'Found {count} potential {kind.replace("_", " ")} match(es). Review before publishing.',
            ))

    return ScanReport(findings)


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _copy_tree(src: Path, dst: Path) -> int:
    count = 0
    if not src.exists():
        return count
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        for p in dst.rglob('*'):
            if p.is_file():
                count += 1
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        count += 1
    return count


def write_starter_data(starter_root: Path) -> int:
    files_written = 0
    data_root = starter_root / 'data'
    knowledge_root = data_root / 'knowledge'

    config = {
        'total_members': 40,
        'base_attendance': 12,
        'last_updated': '2026-01-01',
        'forecast': {'min_attendance': 5, 'max_attendance_factor': 1.25},
        'multipliers': {
            'event_type': {'regular': 1.0, 'trivia': 1.1, 'karaoke': 0.95, 'food': 1.2, 'other': 1.0},
            'context': {'finals': 0.75, 'midterms': 0.9, 'rain': 0.9, 'normal': 1.0},
        },
        'ai_backend': 'ollama',
        'ai_model': 'llama3.1',
        'ai_auto_enable': True,
        'ai_enabled': False,
        'ai_private_active': False,
        'private_consult_active': False,
        'private_consult_owner_id': '',
        'default_log_channel_id': 0,
        'antispam_enabled': True,
        'antispam_notify_channel_id': 0,
        'antispam_notify_channel': 'default-log',
        'antispam_exempt_channel_ids': [],
        'antispam_window_seconds': 10,
        'antispam_max_msgs_in_window': 7,
        'antispam_duplicate_threshold': 2,
        'antispam_links_window_seconds': 30,
        'antispam_max_links_in_window': 3,
        'antispam_alert_cooldown_seconds': 120,
        'antispam_action': 'notify',
        'antispam_timeout_minutes': 10,
        'channels': {'announcements': 0, 'rules': 0, 'e-board': 0, 'default-log': 0},
        'bot_channels': {},
        'voice_channels': {},
        'budget_total': 1000,
        'public_autoresponse_enabled': False,
        'version': '1.0.0',
        'relay_enabled': False,
        'relay_control_guild_id': 0,
        'relay_control_user_id': 0,
        'relay_target_guild_id': 0,
        'relay_target_channel_id': 0,
        'relay_control_channel_id': 0,
        'activity_tracking_enabled': True,
        'activity_default_days': 7,
        'exports_keep_files': 20,
        'backups_keep_files': 5,
        'owner_hints': ['President', 'Treasurer', 'Secretary', 'Vice President'],
        'known_events': ['welcome-week', 'general-meeting', 'social', 'workshop'],
    }
    club_memory = {
        'club_name': 'Sample Organization',
        'university': 'Sample Campus',
        'meeting_day': 'Wednesday',
        'meeting_time': '2:00 PM - 3:30 PM',
        'meeting_room': 'Student Center Room 101',
        'event_types': ['regular', 'food', 'trivia', 'other'],
        'baseline_attendance_default': 12,
        'model_members_default': 40,
        'patterns': {'food': ['ramen', 'snacks'], 'trivia': ['trivia', 'quiz']},
        'notes': 'Replace this file with your own organization details before going live.',
    }
    campus_memory = {
        'campus_name': 'Sample Campus',
        'buildings': {'Student Center': 'Main hub for meetings and club events.'},
        'code_of_conduct': ['Follow university policies.', 'Be respectful in meetings and online spaces.'],
    }
    qa_rules = {
        'rules': [
            {
                'id': 'meeting-when',
                'match_any': ['when do we meet', 'meeting time'],
                'answer': 'Meetings are on Wednesday from 2:00 PM to 3:30 PM in Student Center Room 101.',
            }
        ]
    }
    planning_notes = {
        'schema': 'powerbot.planning_notes.v1',
        'entries': [
            {
                'id': 'welcome-week-example',
                'title': 'Welcome Week planning',
                'date': '2026-09-10',
                'content': 'Confirm table supplies, banner, QR code, and signup sheet.',
            }
        ],
    }
    schedules = {
        'members': {
            'President': [
                {'day': 'Wednesday', 'start': '2:00 PM', 'end': '3:30 PM', 'kind': 'Meeting', 'title': 'Club meeting'}
            ]
        }
    }
    tone = {
        'style': 'helpful, concise, professional',
        'notes': 'Adjust this to match your organization tone.',
        'command_tone': {'default': 'friendly and concise'},
    }
    archive = {'messages': []}
    compiled_rules = {
        'club': club_memory,
        'campus': campus_memory,
        'rules': qa_rules['rules'],
        'planning_notes': planning_notes,
        'schedules': schedules,
        'tone': tone,
    }
    tasks = {'schema': 'powerbot.tasks.v2', 'last_updated': '2026-03-15T00:00:00+00:00', 'tasks': []}
    events: list[dict] = []
    canonical_agenda = {'schema': 'powerbot.canonical_agenda.v1', 'items': []}

    write_targets: dict[Path, dict | list] = {
        data_root / 'config.json': config,
        data_root / 'tasks.json': tasks,
        data_root / 'events.json': events,
        knowledge_root / 'club_memory.json': club_memory,
        knowledge_root / 'campus_memory.json': campus_memory,
        knowledge_root / 'qa_rules.json': qa_rules,
        knowledge_root / 'planning_notes.json': planning_notes,
        knowledge_root / 'schedules.json': schedules,
        knowledge_root / 'tone.json': tone,
        knowledge_root / 'gen_chat_archive.json': archive,
        knowledge_root / 'eboard_talk_archive.json': archive,
        knowledge_root / 'compiled_rules.json': compiled_rules,
        knowledge_root / 'canonical_agenda.json': canonical_agenda,
    }
    for path, payload in write_targets.items():
        _write_json(path, payload)
        files_written += 1

    (data_root / 'eboard_talk_log.txt').write_text(
        "Add your club's recent planning log here if you want richer meeting summaries.\n",
        encoding='utf-8',
    )
    files_written += 1
    return files_written


def build_public_starter(project_root: str | Path, output_dir: str | Path, *, starter_name: str = 'PowerBot-Core-Starter') -> BuildSummary:
    root = Path(project_root).resolve()
    out = Path(output_dir).resolve()
    starter_root = out / starter_name
    if starter_root.exists():
        shutil.rmtree(starter_root)
    starter_root.mkdir(parents=True, exist_ok=True)
    files_written = 0

    for file_name in WHITELIST_TOP_LEVEL_FILES:
        src = root / file_name
        if src.exists():
            files_written += _copy_tree(src, starter_root / file_name)

    for dir_name in WHITELIST_DIRS:
        src = root / dir_name
        if src.exists():
            files_written += _copy_tree(src, starter_root / dir_name)

    files_written += write_starter_data(starter_root)
    manifest = {
        'starter_name': starter_name,
        'source_version': (root / 'VERSION').read_text(encoding='utf-8').strip() if (root / 'VERSION').exists() else 'unknown',
        'notes': 'Generated public starter pack. Replace sample data before going live.',
    }
    _write_json(starter_root / 'starter_manifest.json', manifest)
    files_written += 1
    return BuildSummary(output_root=str(starter_root), files_written=files_written, starter_name=starter_name)
