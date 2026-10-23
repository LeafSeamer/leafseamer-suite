"""明确投影0.2采集器修订；不改旧0.1文件。"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = 'time-collector/0.2.0-draft.1'
FEATURES = ['ordered_stop_cut', 'poll_ordinal_retention']


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()


def build():
    value = json.loads((HERE/'collector.schema.json').read_bytes())
    value['$id'] = 'https://leafseamer.invalid/design/df03-collector/channel-v02.schema.json'
    value['title'] = VERSION
    defs = value['$defs']
    for branch in value['oneOf']:
        frame = defs[branch['$ref'].split('/')[-1]]
        assert frame['properties']['version']['const'] == 'time-collector/0.1.0-draft.1'
        frame['properties']['version']['const'] = VERSION
    for name in ('S1__HELLOBody','S1__ACCEPTBody'):
        defs[name]['properties']['version']['const'] = VERSION
        defs[name]['properties']['features']['allOf'] += [{'contains':{'const':f}} for f in FEATURES]
    poll = defs['S1__PollIntent']
    poll['properties']['poll_ordinal'] = {'$ref':'#/$defs/S1__Positive'}
    poll['required'].append('poll_ordinal')
    stop = defs['S1__Stop']
    del stop['properties']['poll_refs']
    stop['required'].remove('poll_refs')
    for name in ('cut_sequence','last_poll_ordinal'):
        stop['properties'][name] = {'$ref':'#/$defs/S1__UInt'}
        stop['required'].append(name)
    ack = defs['S1__STOP_ACKBody']
    del ack['properties']['consumed_poll_refs']
    ack['required'].remove('consumed_poll_refs')
    ack['properties'].update(received_through_sequence={'$ref':'#/$defs/S1__Positive'},
                             last_poll_ordinal={'$ref':'#/$defs/S1__UInt'}, gate_closed={'const':True})
    ack['required'] += ['received_through_sequence','last_poll_ordinal','gate_closed']
    return value


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--check',action='store_true'); args=parser.parse_args()
    result=encoded(build())
    if args.check:
        assert (HERE/'channel-v02.schema.json').read_bytes() == result
    else:
        (HERE/'channel-v02.schema.json').write_bytes(result)
