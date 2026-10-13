"""Conservative source attribution independent of the reflector's own role claims."""
import json
import re

from .policy import Rejected, digest, redact


LESSON_KINDS = ('user_preference', 'observed_result', 'verified_technique', 'manual_lesson', 'consolidation')
QUOTED = re.compile(r'```[\s\S]*?```|<untrusted_text>[\s\S]*?</untrusted_text>|^\s*>[^\n]*(?:\n|$)', re.M)
CONTEXT = re.compile(r'^\s*(?:<environment_context>|<external_codex_apps_|# AGENTS\.md instructions|<app-context>)')


def records(source):
    try:
        value = json.loads(source)
        if isinstance(value, dict) and value.get('episode_version') == 1 and isinstance(value.get('records'), list):
            return value['records']
    except (ValueError, TypeError):
        pass
    return None


def _texts(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(part['text'] for part in content if isinstance(part, dict)
                         and part.get('type') in ('input_text', 'output_text', 'text')
                         and isinstance(part.get('text'), str))
    return ''


def normalize(source, *, origin='transcript'):
    """Only the system's stored envelopes are reused, never envelopes from raw input."""
    output, seen = [], set()

    def add(kind, text, verified=False):
        text = redact(text).strip()
        if not text:
            return
        rid = digest([kind, text, bool(verified)])[:24]
        if rid not in seen:
            output.append(dict(id=rid, kind=kind, text=text, verified=bool(verified)))
            seen.add(rid)

    def user(text):
        if CONTEXT.match(text):
            add('context', text)
            return
        pos = 0
        for match in QUOTED.finditer(text):
            add('user', text[pos:match.start()])
            add('quoted', match[0])
            pos = match.end()
        add('user', text[pos:])

    if origin in ('manual', 'library'):
        if origin == 'manual':
            add('manual', source)
        else:
            for line in source.splitlines():
                add('library', line)
    else:
        for line in source.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                add('unknown', line)
                continue
            if not isinstance(record, dict):
                add('unknown', line)
                continue
            payload = record.get('payload', {})
            if not isinstance(payload, dict):
                payload = {}
            typ = payload.get('type')
            if record.get('type') == 'response_item' and typ == 'message':
                text = _texts(payload.get('content'))
                if payload.get('role') == 'user':
                    user(text)
                elif payload.get('role') == 'assistant':
                    add('assistant', text)
                else:
                    add('context', text)
            elif record.get('type') == 'response_item' and typ in ('function_call_output', 'custom_tool_call_output'):
                value = payload.get('output', '')
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                try:
                    result = json.loads(text)
                except ValueError:
                    result = None
                # Tool exit success is an observation, not proof the assistant's conclusion is true.
                verified = isinstance(result, dict) and type(result.get('exit_code')) is int and result['exit_code'] == 0
                add('tool_result', text, verified)
            elif record.get('type') == 'event_msg' and typ in ('user_message', 'assistant_message'):
                text = _texts(payload.get('message', ''))
                user(text) if typ == 'user_message' else add('assistant', text)
            elif record.get('type') in ('user', 'assistant') and isinstance(record.get('message'), str):
                user(record['message']) if record['type'] == 'user' else add('assistant', record['message'])
            elif record.get('type') not in ('session_meta', 'turn_context', 'world_state', 'token_usage_record', 'event_msg'):
                add('unknown', line)
    return json.dumps(dict(episode_version=1, origin=origin, records=output), ensure_ascii=False, separators=(',', ':'))


def provenance(source, proposal):
    data = records(source)
    if data is None:
        return {'kind': 'legacy_untyped', 'records': []}
    quote = proposal.get('evidence', '')
    ids = proposal.get('evidence_ids')
    if ids is None:
        # Compatibility for v1 staged proposals: attribute from exact record text,
        # never from a model-provided role. Ambiguous quotations require explicit ids.
        matches = [record for record in data if quote and quote in record['text']]
        if len(matches) != 1:
            raise Rejected('Evidence needs unambiguous source record ids.')
        ids = [matches[0]['id']]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        raise Rejected('Evidence requires 1-4 distinct source ids.')
    mapping = {record['id']: record for record in data}
    try:
        selected = [mapping[rid] for rid in ids]
    except (KeyError, TypeError):
        raise Rejected('Unknown evidence record id.') from None
    if quote not in '\n'.join(record['text'] for record in selected):
        raise Rejected('Evidence must quote selected record text, not envelope metadata.')
    kinds = {record['kind'] for record in selected}
    default = {'user': 'user_preference', 'tool_result': 'observed_result', 'manual': 'manual_lesson', 'library': 'consolidation'}
    lesson = proposal.get('lesson_kind') or (default.get(next(iter(kinds))) if len(kinds) == 1 else None)
    valid = ((lesson == 'user_preference' and kinds == {'user'})
             or (lesson == 'observed_result' and kinds == {'tool_result'})
             or (lesson == 'manual_lesson' and kinds == {'manual'})
             or (lesson == 'consolidation' and kinds == {'library'})
             or (lesson == 'verified_technique' and kinds == {'user', 'tool_result'}
                 and any(r['kind'] == 'tool_result' and r['verified'] for r in selected)))
    if not valid:
        raise Rejected('Lesson kind is not supported by these source roles.')
    return {'kind': lesson, 'records': selected}
