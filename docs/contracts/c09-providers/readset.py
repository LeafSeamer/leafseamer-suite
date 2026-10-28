"""14类提供者的进程内读集参考；不实现来源读取、生产审批或发送门。"""
import copy
import hashlib
import json
import re
from pathlib import Path
import threading
import time
import rfc8785

ROOT=Path(__file__).resolve().parent
BINDINGS=json.loads((ROOT/'source/bindings.json').read_bytes())
SELECTION=json.loads((ROOT/'source/selection.json').read_bytes())

class Unavailable(ValueError):pass
def need(ok,reason):
    if not ok:raise Unavailable(reason)

def bounded(value,limit=262144):
    todo=[(value,0)];count=0;chars=0
    while todo:
        item,depth=todo.pop();count+=1;need(count<=32768 and depth<=48,'value_budget')
        if type(item) is dict:
            need(all(type(k) is str for k in item),'json_key');chars+=sum(len(k) for k in item)
            todo.extend((v,depth+1) for v in item.values())
        elif type(item) is list:todo.extend((v,depth+1) for v in item)
        else:
            need(item is None or type(item) in [str,bool,int,float],'json_value')
            if type(item) is str:chars+=len(item)
        need(chars<=limit,'value_budget')
    try:raw=rfc8785.dumps(value)
    except (ValueError,TypeError,OverflowError) as e:raise Unavailable('canonical_value') from e
    need(len(raw)<=limit,'value_budget');return raw

def digest(value):return hashlib.sha256(bounded(value)).hexdigest()
def assignments(method):
    need(method in BINDINGS['methods'],'method')
    variant=BINDINGS['methods'][method]['variant'];plan=BINDINGS['plans'][variant];out={'root':{}}
    for field,rule in plan['fields'].items():out.setdefault('root' if rule['kind']=='source' else rule['provider'],{})[field]=rule
    return variant,plan['source_model'],out

def reference(ref):
    keys={'authority_service_id','database_instance_id','entity_kind','entity_id','entity_epoch','revision','content_digest'}
    need(type(ref) is dict and set(ref)==keys,'source_ref')
    need(all(type(v) is str and re.fullmatch(r'[A-Za-z0-9._-]{1,128}',v) for k,v in ref.items() if k not in ['revision','content_digest']),'source_identity')
    need(type(ref['revision']) is str and ref['revision'].isascii() and ref['revision'].isdigit() and
         0<len(ref['revision'])<=20 and (ref['revision']=='0' or not ref['revision'].startswith('0')),'source_revision')
    h=ref['content_digest'];need(type(h) is str and len(h)==64 and all(c in '0123456789abcdef' for c in h),'source_digest')

class Ticket:
    __slots__=()
class Candidate:
    __slots__=()

class ReadSet:
    """只由可信宿主建立；expected_sources是固定读取计划，不是面板自报数据。"""
    def __init__(self,context,expected_sources,source_validator,result_validator,*,ttl_ms=2000,clock=time.monotonic_ns):
        bounded(context);bounded(expected_sources,1048576)
        need(type(context) is dict and set(context)=={'selection','authority','method','request_id','input_digest','public_binding_digest','activation_digest','installation_digest','approval_digest','authorization_digest','scope'},'context_fields')
        need(context['selection']==SELECTION,'selection')
        need(type(context['request_id']) is str and 0<len(context['request_id'])<=128,'request_id')
        for key in ['input_digest','public_binding_digest','activation_digest','installation_digest','approval_digest','authorization_digest']:
            h=context[key];need(type(h) is str and len(h)==64 and all(c in '0123456789abcdef' for c in h),'context_digest')
        scope=context['scope'];need(type(scope) is dict and set(scope)=={'authority_service_id','database_instance_id'} and all(type(v) is str and 0<len(v)<=128 for v in scope.values()),'scope')
        self.variant,self.source_model,self.parts=assignments(context['method'])
        need(context['authority']==BINDINGS['methods'][context['method']]['authority'],'method_authority')
        need(type(expected_sources) is dict and set(expected_sources)==set(self.parts),'provider_set')
        count=0
        for provider,refs in expected_sources.items():
            need(type(refs) is list and 1<=len(refs)<=64,'source_count');count+=len(refs);seen=set()
            for item in refs:
                need(type(item) is dict and set(item)=={'model','ref'},'source_plan')
                need(type(item['model']) is str and 0<len(item['model'])<=128,'source_model');reference(item['ref'])
                need(all(item['ref'][k]==v for k,v in scope.items()),'source_scope')
                key=tuple(item['ref'][k] for k in ['entity_kind','entity_id','entity_epoch','revision'])
                need(key not in seen,'duplicate_source');seen.add(key)
        need(count<=256 and len(expected_sources['root'])==1 and expected_sources['root'][0]['model']==self.source_model,'root_source')
        need(callable(source_validator) and callable(result_validator),'validator_required')
        need(type(ttl_ms) is int and 1<=ttl_ms<=2000,'deadline_budget')
        now=clock();need(type(now) is int and now>=0,'clock')
        self._context=copy.deepcopy(context);self.context_digest=digest(context);self._sources=copy.deepcopy(expected_sources)
        self._source_validator=source_validator;self._result_validator=result_validator;self._clock=clock
        self._last=now;self._expires=now+ttl_ms*1000000;self._lock=threading.RLock()
        self._state='reading';self._tickets={};self._issued=set();self._inflight=set();self._values={};self._candidate=None
    def _invalidate(self):
        self._state='invalid';self._tickets.clear();self._values.clear();self._candidate=None
    def invalidate(self):
        with self._lock:self._invalidate()
    def _current(self):
        need(self._state in ['reading','sealed'],'readset_closed')
        now=self._clock()
        if type(now) is not int or now<self._last or now>=self._expires:
            self._invalidate();raise Unavailable('readset_expired')
        self._last=now
    def ticket(self,provider):
        with self._lock:
            self._current();need(self._state=='reading','readset_sealed')
            need(provider in self.parts and provider not in self._issued,'provider_ticket')
            token=Ticket();self._issued.add(provider);self._tickets[token]=provider;return token
    def fail(self,ticket):
        with self._lock:
            self._current();need(type(ticket) is Ticket and ticket in self._tickets,'provider_ticket');self._invalidate()
    def provide(self,ticket,sources,fields):
        with self._lock:
            self._current();need(self._state=='reading','readset_sealed')
            need(type(ticket) is Ticket and ticket in self._tickets and ticket not in self._inflight,'provider_ticket')
            provider=self._tickets[ticket];self._inflight.add(ticket)
        try:
            bounded(sources,1048576);bounded(fields);sources=copy.deepcopy(sources);fields=copy.deepcopy(fields)
            need(type(sources) is list and len(sources)==len(self._sources[provider]),'source_set')
            need(type(fields) is dict and set(fields)==set(self.parts[provider]),'field_set')
            for supplied,expected in zip(sources,self._sources[provider]):
                need(type(supplied) is dict and set(supplied)=={'model','ref','value'},'source_record')
                need(supplied['model']==expected['model'] and supplied['ref']==expected['ref'],'source_binding')
                need(digest(supplied['value'])==expected['ref']['content_digest'],'source_bytes')
                # 验证器须失败抛异常；复制参数防止适配器意外改动已绑定字节。
                need(self._source_validator(expected['model'],copy.deepcopy(supplied['value'])) is True,'source_schema')
            if provider=='root':
                original=sources[0]['value']
                for field,rule in self.parts['root'].items():
                    value=original
                    for segment in rule['path'].split('.'):
                        need(type(value) is dict and segment in value,'direct_source_path');value=value[segment]
                    need(bounded(fields[field])==bounded(value),'direct_source_value')
            with self._lock:
                self._current();need(self._state=='reading' and ticket in self._tickets,'provider_ticket')
                proposed=dict(self._values,**{provider:fields});bounded(proposed,1048576)
                self._values=proposed;self._tickets.pop(ticket)
        except Exception:
            with self._lock:self._invalidate()
            raise
        finally:
            with self._lock:self._inflight.discard(ticket)
    def seal(self):
        with self._lock:
            self._current();need(self._state=='reading','readset_sealed')
            need(set(self._values)==set(self.parts) and not self._inflight,'incomplete_readset')
            values={field:copy.deepcopy(value) for part in self._values.values() for field,value in part.items()}
            self._state='validating'
        try:
            bounded(values);need(self._result_validator(self.variant,copy.deepcopy(values)) is True,'result_schema')
            with self._lock:
                need(self._state=='validating','readset_closed');self._state='reading';self._current()
                self._state='sealed';self._candidate=Candidate();self._output=bounded(values);return self._candidate
        except Exception:
            with self._lock:self._invalidate()
            raise
    def consume(self,context,candidate):
        with self._lock:
            self._current();need(self._state=='sealed' and type(candidate) is Candidate and candidate is self._candidate,'candidate_binding')
            if digest(context)!=self.context_digest:
                self._invalidate();raise Unavailable('context_changed')
            result=json.loads(self._output);self._state='consumed';self._candidate=None;self._values.clear();return result
