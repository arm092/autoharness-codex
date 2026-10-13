"""Bounded source selection and complete skill packages, shared by admission and execution."""
import json
from dataclasses import dataclass

from .episode import normalize, records
from .policy import Rejected, frontmatter
from .retrieval import rank


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def size(value):
    return len(encoded(value).encode('utf-8'))


@dataclass
class Plan:
    prompt: str
    stats: dict
    eligible: bool
    input_estimate: int
    output_allowance: int


def _fit_record(record, cap):
    if size(record)<=cap:
        return dict(record)
    item=record | {'truncated':True}
    text=record['text']
    lo,hi=0,len(text)
    while lo<hi:
        mid=(lo+hi+1)//2
        item['text']=text[:mid]
        if size(item)<=cap:
            lo=mid
        else:
            hi=mid-1
    item['text']=text[:lo]
    return item if len(item['text'].strip())>=8 and size(item)<=cap else None


def build(source, skills, kind, settings, instructions, schema_bytes):
    source=source if records(source) is not None else normalize(source,origin='manual')
    envelope=json.loads(source)
    all_records=envelope['records']
    priorities={'user':5,'manual':5,'library':5,'tool_result':3}
    candidates=[(i,r) for i,r in enumerate(all_records) if r['kind'] in priorities]
    candidates.sort(key=lambda pair:(-(priorities[pair[1]['kind']]+int(pair[1].get('verified',False))),-pair[0]))
    selected=[]
    for i,record in candidates:
        available=settings.source_bytes-size({'episode_version':1,'origin':envelope.get('origin','legacy'),
                                             'records':[r for _,r in selected]})-2
        item=_fit_record(record,available)
        if item:
            selected.append((i,item))
    selected.sort(key=lambda pair:pair[0])
    episode={'episode_version':1,'origin':envelope.get('origin','legacy'),'records':[r for _,r in selected]}
    # The origin field is part of the source byte cap as well.
    while selected and size(episode)>settings.source_bytes:
        selected.pop(0)
        episode['records']=[r for _,r in selected]
    metadata=[]
    for skill in skills:
        fields,_=frontmatter(skill['body'])
        metadata.append({'name':skill['name'],'description':fields.get('description',''),
                         'category':fields.get('category','general'),'hash':skill['hash']})
    scores={}
    for _,record in selected:
        for hit in rank(record['text'][:1500],metadata,limit=None,min_coverage=0.05):
            scores[hit['name']]=max(scores.get(hit['name'],0),hit['relevance'])
    by_name={skill['name']:skill for skill in skills}
    ordered=sorted(metadata,key=lambda m:(-scores.get(m['name'],0),m['name']))
    library=[]
    for meta in ordered:
        if kind!='curate' and meta['name'] not in scores:
            continue
        skill=by_name[meta['name']]
        item={key:skill[key] for key in ('name','hash','body','files')}
        item['source_kind']=skill.get('provenance',{}).get('kind','legacy_untyped')
        if size(library+[item])<=settings.library_bytes:
            library.append(item)
    index=[]
    for meta in ordered:
        line=f"{meta['name']} [{meta['hash']}]: {meta['description'][:120]}"
        if len(('\n'.join(index)+'\n'+line).encode('utf-8'))>6000:
            break
        index.append(line)
    data={'job':kind,'scope':'global' if getattr(settings,'_global_job',False) else 'project',
          'EPISODE':episode,'MANAGED_LIBRARY':library,'LIBRARY_INDEX':'\n'.join(index)}

    def prompt():
        return instructions+'\nDATA\n'+encoded(data)

    while size_prompt:=len(prompt().encode('utf-8')):
        if size_prompt<=settings.prompt_bytes:
            break
        if library:
            library.pop()
        elif len(index)>1:
            index.pop()
            data['LIBRARY_INDEX']='\n'.join(index)
        elif episode['records']:
            # Remove the least informative record, preserving original order of survivors.
            lowest=min(range(len(episode['records'])),key=lambda i:(priorities[episode['records'][i]['kind']],i))
            episode['records'].pop(lowest)
        else:
            raise Rejected('Prompt limit is too small for the required instructions.')
    final=prompt()
    stats={'original_source_bytes':len(source.encode('utf-8')),'source_bytes':size(episode),
           'original_library_bytes':size([{k:s[k] for k in ('name','hash','body','files')} for s in skills]),
           'library_bytes':size(library),'prompt_bytes':len(final.encode('utf-8')),
           'selected_records':len(episode['records']),'omitted_records':len(all_records)-len(episode['records']),
           'truncated_records':sum(bool(r.get('truncated')) for r in episode['records']),
           'selected_skills':len(library),'omitted_skills':len(skills)-len(library),
           'index_skills':len(index),'index_omitted':len(metadata)-len(index)}
    # Deliberately byte-based safety estimate, not an exact tokenizer count. Add
    # schema and host-envelope allowance; actual CLI usage is recorded separately.
    estimate=stats['prompt_bytes']+schema_bytes+4096
    return Plan(final,stats,bool(episode['records']),estimate,settings.output_tokens)
