"""Deterministic admission checks. Heuristics are filters, not a security proof."""
import hashlib
import json
import os
import sys
import re
from pathlib import Path


class Rejected(ValueError):
    pass


class Conflict(Rejected):
    pass


SECRET_RULES = [
    r'context_token:\s*[a-f0-9]{32}',
    r'gh[pousr]_[A-Za-z0-9]{20,}', r'github_pat_[A-Za-z0-9_]{20,}',
    r'AKIA[0-9A-Z]{16}', r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',
    r'xox[abprs]-[A-Za-z0-9-]{10,}', r'(?i)bearer\s+[A-Za-z0-9._-]{12,}',
    r'(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*[\'"]?[A-Za-z0-9._/+\-]{12,}',
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)',
]
PII_RULES = [r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
             r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)',
             r'(?<!\d)(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)']
DANGEROUS = re.compile(
    r'ignore\s+(?:all\s+)?previous\s+instructions|'
    r'(?:bypass|override)\b.{0,30}(?:system|sandbox|permissions)|'
    r'\brm\s+-[rf]{1,2}\s+(?:/|~|\$HOME|\*)|\bdrop\s+table\b|'
    r'(?:curl|wget)\s+[^\n]*\|\s*(?:sh|bash)|'
    r'Remove-Item\b[^\n]*-Recurse|\b(?:eval|exec)\s*\(', re.I)
NAME = re.compile(r'^[a-z0-9][a-z0-9._-]{0,99}$')
RESERVED = {'con', 'prn', 'aux', 'nul'} | {f'{s}{i}' for s in ('com', 'lpt') for i in range(1, 10)}


def digest(value):
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def redact(text):
    for rule in SECRET_RULES:
        text = re.sub(rule, '[REDACTED:secret]', text)
    for rule in PII_RULES:
        text = re.sub(rule, '[REDACTED:personal]', text)
    return text


def safe_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name) or '..' in name or name.endswith('.') \
            or name.split('.')[0] in RESERVED:
        raise Rejected('Invalid portable name.')
    return name


def safe_relative(value):
    if not isinstance(value, str) or '\\' in value:
        raise Rejected('Invalid support file path.')
    parts = value.split('/')
    if len(parts) < 2 or parts[0] not in ('references', 'scripts', 'templates', 'assets'):
        raise Rejected('Support files must stay in approved directories.')
    for part in parts:
        safe_name(part)
    if value.startswith('references/evidence-'):
        raise Rejected('Evidence files are owned by the promoter.')
    return value


def safe_directory(path):
    """Reject every existing symlink/junction component before creating owned storage."""
    path = Path(os.path.abspath(path))
    for component in [*reversed(path.parents), path]:
        if component.exists() or component.is_symlink():
            stat = component.lstat()
            if component.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                # macOS owns these root-level aliases. Canonicalize only the exact
                # root-owned OS links; user-controlled symlinks still fail below.
                aliases = {'/var': '/private/var', '/tmp': '/private/tmp', '/etc': '/private/etc'}
                target = aliases.get(str(component))
                if sys.platform == 'darwin' and target and component.is_symlink() and stat.st_uid == 0:
                    actual = os.path.abspath(component.parent/os.readlink(component))
                    if actual == target:
                        return safe_directory(Path(target)/path.relative_to(component))
                raise Rejected('Data paths cannot contain symlinks or junctions.')
    return path


def frontmatter(body):
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', body, re.S)
    if not match:
        raise Rejected('SKILL.md requires frontmatter.')
    fields = {}
    for line in match[1].splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip()] = value.strip().strip('\'"')
    return fields, body[match.end():]


def validate_content(name, body, files, *, scope, allow_scripts=False):
    safe_name(name)
    if not isinstance(body, str) or len(body.encode('utf-8')) > 100_000:
        raise Rejected('Invalid or oversized SKILL.md.')
    fields, rest = frontmatter(body)
    if fields.get('name') != name:
        raise Rejected('Frontmatter name must match skill name.')
    safe_name(fields.get('category', ''))
    desc = fields.get('description', '')
    if not 10 <= len(desc) <= 240 or '\n' in desc:
        raise Rejected('Description must be a 10-240 character trigger.')
    if sum(bool(line.strip()) for line in rest.splitlines()) > 40:
        raise Rejected('Keep SKILL.md to 40 nonempty body lines; use references.')
    if not isinstance(files, dict) or len(files) > 8:
        raise Rejected('At most 8 support files are allowed.')
    total = 0
    for rel, content in files.items():
        safe_relative(rel)
        if rel not in body or not isinstance(content, str):
            raise Rejected('Each support file must be referenced in SKILL.md.')
        size = len(content.encode('utf-8'))
        if size > 64_000:
            raise Rejected('Support file exceeds 64 KB.')
        total += size
        if rel.startswith('scripts/') and not allow_scripts:
            raise Rejected('Scripts require explicit manual admission.')
    if total > 256_000:
        raise Rejected('Support files exceed 256 KB.')
    # Detect dangling pointers even when a remove_file or patch omitted a carried file.
    for ref in re.findall(r'\b(?:references|scripts|templates|assets)/[a-zA-Z0-9._/-]+', body):
        ref = ref.rstrip('.')
        if not ref.startswith('references/evidence-') and ref not in files:
            raise Rejected('SKILL.md references a missing support file.')
    for content in [body, *files.values()]:
        if any(re.search(rule, content) for rule in SECRET_RULES):
            raise Rejected('A known secret was detected.')
        if DANGEROUS.search(content):
            raise Rejected('A dangerous instruction pattern was detected.')
        if re.search(r'\b(?:TODO|FIXME|TBD)\b', content):
            raise Rejected('Unfinished placeholders are not skills.')
        if scope == 'global' and re.search(r'[A-Za-z]:[/\\]|/(?:home|Users|root|workspace)/', content):
            raise Rejected('Global skills cannot contain project-local absolute paths.')
    return fields
