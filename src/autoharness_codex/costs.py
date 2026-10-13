"""Transactional UTC-day model admission. Estimates and provider reports stay distinct."""
import json
from datetime import datetime, timezone


def day(now):
    return datetime.fromtimestamp(now,timezone.utc).date().isoformat()


def reserve(db,scope,attempt,job,plan,now,limit):
    charge=plan.input_estimate+plan.output_allowance
    used=db.execute('SELECT COALESCE(SUM(charged),0) FROM usage WHERE scope=? AND day=?',(scope,day(now))).fetchone()[0]
    if used+charge>limit:
        return False
    db.execute('INSERT INTO usage(scope,attempt,job,day,reserved,charged,state,context) VALUES (?,?,?,?,?,?,?,?)',
               (scope,attempt,job,day(now),charge,charge,'reserved',json.dumps(plan.stats)))
    return True


def settle(db,scope,attempt,usage=None):
    row=db.execute('SELECT * FROM usage WHERE scope=? AND attempt=?',(scope,attempt)).fetchone()
    if not row or row['actual_input'] is not None:
        return
    keys=('input_tokens','cached_input_tokens','output_tokens')
    valid=isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in keys)
    valid=valid and usage['cached_input_tokens']<=usage['input_tokens']
    if valid:
        db.execute("UPDATE usage SET charged=?,actual_input=?,actual_cached=?,actual_output=?,state='reported' WHERE scope=? AND attempt=?",
                   (usage['input_tokens']+usage['output_tokens'],usage['input_tokens'],usage['cached_input_tokens'],
                    usage['output_tokens'],scope,attempt))
    else:
        db.execute("UPDATE usage SET state='estimated' WHERE scope=? AND attempt=?",(scope,attempt))


def summary(db,scope,limit,now):
    rows=db.execute('SELECT * FROM usage WHERE scope=? AND day=?',(scope,day(now))).fetchall()
    charged=sum(r['charged'] for r in rows)
    return {'day_utc':day(now),'daily_limit':limit,'charged_tokens':charged,'remaining_tokens':max(0,limit-charged),
            'reported_input_tokens':sum(r['actual_input'] or 0 for r in rows),
            'reported_cached_tokens':sum(r['actual_cached'] or 0 for r in rows),
            'reported_output_tokens':sum(r['actual_output'] or 0 for r in rows),
            'reported_attempts':sum(r['state']=='reported' for r in rows),
            'estimated_attempts':sum(r['state']!='reported' for r in rows),
            'reserved_tokens':sum(r['charged'] for r in rows if r['state']=='reserved'),
            'overrun_attempts':sum(r['charged']>r['reserved'] for r in rows),
            'accounting':'Provider-reported input + output, or conservative byte-based reservation when unavailable; not billing currency.'}
