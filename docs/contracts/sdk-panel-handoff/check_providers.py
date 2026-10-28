"""实际调用固定提供者的选择边界；不迁移或重标旧提供者。"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from jsonschema.exceptions import ValidationError

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def run(root):
    sys.path.insert(0,str(root/'contracts/publication-source'))
    import store as S
    PF=load('publication_examples',root/'contracts/publication-source/fixtures.py')
    sys.path.insert(0,str(root/'contracts/panel-dynamic'))
    import provider as P
    F=load('dynamic_examples',root/'contracts/panel-dynamic/fixtures.py')
    current=json.loads((root/'contracts/panel-wire/contract/selection.json').read_bytes())
    previous=json.loads((root/'contracts/panel-integration/preview/selection.json').read_bytes())
    checks=[]
    def check(name,value):
        assert value,name
        checks.append(dict(name=name,passed=True))
    record=PF.example()
    check('发布原件仍绑定panel3',record['selection']==previous)
    check('旧发布原件仍可验证',S.validate(copy.deepcopy(record))==record)
    bad=copy.deepcopy(record);bad['selection']=current
    bad['record_digest']=S.digest({k:v for k,v in bad.items() if k!='record_digest'})
    try:S.validate(bad)
    except ValidationError:check('重摘要后不可重标发布选择',True)
    else:raise AssertionError('重标发布选择未拒绝')
    f=F.fixture();check('动态提供者仍绑定panel3',P.SELECTION==previous)
    P.context(f['context'],f['manifest']);check('原动态上下文仍可验证',True)
    changed=copy.deepcopy(f['context']);changed['selection']=current
    try:P.context(changed,f['manifest'])
    except P.Unavailable as e:check('动态提供者拒绝panel4',str(e)=='selection')
    else:raise AssertionError('动态选择未拒绝')
    return dict(all_passed=True,cases_passed=len(checks),checks=checks,provider_selection=previous,current_selection=current,
                provider_migration_complete=False,validator_subprocess_calls=0,production_authorization_executed=False)

if __name__=='__main__':print(json.dumps(run(Path(sys.argv[1]).resolve()),ensure_ascii=False))
