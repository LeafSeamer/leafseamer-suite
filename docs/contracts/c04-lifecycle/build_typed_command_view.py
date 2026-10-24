"""复用单一命令类型图，约束完整公开记录的存储字段映射。"""
import argparse
from pathlib import Path
import build_typed_controller as B
import build_command_contract as C
HERE=Path(__file__).resolve().parent
SOURCES=list(dict.fromkeys(B.SOURCES+C.SOURCES+[Path(__file__),HERE/'typed-command-view.sql']))
def build():return B.build()+b'\n'+(HERE/'typed-command-view.sql').read_bytes()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'controller-command-view.sql'
    if a.check:assert path.read_bytes()==build()
    else:path.write_bytes(build())
