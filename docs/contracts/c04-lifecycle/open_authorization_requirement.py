"""仅核需求对象的格式、关联和半开窗口，不读取权威或判定允许开闸。"""
import hashlib
import jsonschema
import rfc8785
import build_open_authorization as B
def digest(value):return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def seal(value):
    value['requirement_digest']=digest({k:v for k,v in value.items() if k!='requirement_digest'});return value
def validate_requirement(value,now):
    schema=B.build();schema['$ref']='#/$defs/Requirement';schema.pop('not')
    jsonschema.Draft202012Validator(schema).validate(value)
    jsonschema.Draft202012Validator(B.build()['$defs']['Counter']).validate(now)
    if value['requirement_digest']!=digest({k:v for k,v in value.items() if k!='requirement_digest'}):raise ValueError('requirement_digest')
    if value['holder_evidence'] is not None and value['holder_evidence']['principal']!=value['holder']:raise ValueError('holder_identity')
    if not int(value['selected_tick_ns'])<=int(now)<int(value['expires_tick_ns']):raise ValueError('requirement_window')
    # 成功只表示可交给取证器解析；绝不返回allowed、ready或GateAccess。
    return None
