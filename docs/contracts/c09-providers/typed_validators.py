"""固定panel4模型的来源与结果验证；动态槽必须逐项进入可信批准接口。"""
import copy
import hashlib
import json
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry
from referencing.exceptions import NoSuchResource
import readset as R

MODEL_SHA256='6976abefa2ed3d3e5ae8893fc23519969b07daac931a146c4c7fafd4aa67e773'
FIXED_SELECTION=dict(contract_id='leafseamer.api.v1.panel4',contract_digest='sha256:decbdf83f91486da0f473d0cbd5ad20efd188cc681de3b04a39921a4e72fa4fd')

def no_resource(uri):raise NoSuchResource(ref=uri)

def display_error(view,value):
    if view in ['ClockView','ClockAssessmentView'] and value['status']=='conditional':
        lo=int(value['reference_utc']['lower_ns']);hi=int(value['reference_utc']['upper_ns'])
        mid=int(value['estimated_utc_ns']);radius=int(value['error_radius_ns'])
        if not lo<=mid<=hi or radius<max(mid-lo,hi-mid):return 'clock_interval'
    if view=='CommandView':
        if (value['phase']=='finished')==(value['outcome']=='pending'):return 'phase'
        if value['outcome'] in ['unknown','blocked','expired'] and value['automation_continuation']!='paused_latched':return 'continuation'
        if value['outcome']=='unknown' and (value['effect_status']=='not_sent' or (value['resource_status']=='clear' and value['resolution_summary'] is None)):return 'unknown'
    if view=='PreflightView' and value['passed'] and any(c['status']!='passed' for c in value['checks']):return 'preflight'
    if view=='RecoveryOperationView':
        if int(value['committed_run_revision'])<=int(value['previous_run_revision']):return 'revision'
        if value['new_execution_id'] is None and (value['visible_new_command_ids'] or value['has_hidden_commands']):return 'execution'
    return None

def dynamic_slots(view,value):
    """只枚举固定模型中的动态语义位置，不按任意数据键名猜测Schema。"""
    if view=='CapabilityView':
        for i,action in enumerate(value['actions']):
            yield f'/actions/{i}/parameters_schema_ref','schema_ref',action['parameters_schema_ref']
            if action['result_schema_ref'] is not None:yield f'/actions/{i}/result_schema_ref','schema_ref',action['result_schema_ref']
        for i,trigger in enumerate(value['triggers']):yield f'/triggers/{i}/payload_schema_ref','schema_ref',trigger['payload_schema_ref']
        yield '/state_schema_ref','schema_ref',value['state_schema_ref']
    elif view=='ObservationView':yield '/values','qualified',value['values']
    elif view in ['DraftDefinitionView','PublishedDefinitionView']:
        yield '/content','raw',value['content'];yield '/metadata','raw',value['metadata']
    elif view=='RecoveryPlanView':
        for i,item in enumerate(value['items']):
            for j,evidence in enumerate(item['evidence_summaries']):yield f'/items/{i}/evidence_summaries/{j}','qualified',evidence
            if item['parameters_summary'] is not None:yield f'/items/{i}/parameters_summary','qualified',item['parameters_summary']

class Contract:
    def __init__(self,models_bytes,selection):
        R.need(type(models_bytes) is bytes and hashlib.sha256(models_bytes).hexdigest()==MODEL_SHA256,'fixed_models')
        R.need(selection==R.SELECTION==FIXED_SELECTION,'selection')
        self._models=json.loads(models_bytes);self._defs=self._models['$defs'];self._validators={}
        R.need(len(self._defs)==1463,'model_count')
        self._registry=Registry(retrieve=no_resource)
    def validate(self,model,value):
        R.bounded(value);R.need(type(model) is str and model in self._defs,'model_name')
        if model not in self._validators:
            self._validators[model]=Draft202012Validator({'$ref':'#/$defs/'+model,'$defs':self._defs},registry=self._registry,format_checker=FormatChecker())
        return self._validators[model].is_valid(value)
    def bind(self,method,dynamic_validator=None):return SelectedValidators(self,method,dynamic_validator)
    def readset(self,context,expected_sources,dynamic_validator=None,**limits):
        R.bounded(context);context=copy.deepcopy(context)
        return self.bind(context['method'],dynamic_validator).readset(context,expected_sources,**limits)

class SelectedValidators:
    def __init__(self,contract,method,dynamic_validator):
        self._contract=contract;self._method=method;self._variant,self._root,_=R.assignments(method)
        R.need(dynamic_validator is None or callable(dynamic_validator),'dynamic_validator')
        self._dynamic=dynamic_validator
    def readset(self,context,expected_sources,*,source_guard=None,result_guard=None,**limits):
        R.need(context['selection']==R.SELECTION==FIXED_SELECTION,'selection')
        R.need(context['method']==self._method,'validator_method')
        R.need(callable(source_guard) and callable(result_guard),'domain_guards_required')
        R.bounded(context);fixed=copy.deepcopy(context)
        def source(model,value):
            return self.source(model,value) and source_guard(copy.deepcopy(fixed),model,copy.deepcopy(value)) is True
        def result(view,value):
            return self.result(view,value) and result_guard(copy.deepcopy(fixed),view,copy.deepcopy(value)) is True
        return R.ReadSet(fixed,expected_sources,source,result,**limits)
    def source(self,model,value):return self._contract.validate(model,value)
    def result(self,view,value):
        R.need(view==self._variant,'method_result');R.bounded(value);snapshot=copy.deepcopy(value)
        if not self._contract.validate('panel3__Result_'+view,snapshot):return False
        if display_error(view,snapshot) is not None:return False
        for path,kind,item in dynamic_slots(view,snapshot):
            # 缺批准入口不是静态Schema成功；不能默认放行空layout或自报SchemaRef。
            if self._dynamic is None or self._dynamic(self._method,path,kind,copy.deepcopy(item)) is not True:return False
        return True
