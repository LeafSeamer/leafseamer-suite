"""238表固定attempt库存候选；追加约束，不改旧组合DDL。"""
import argparse
from pathlib import Path
import build_typed_command_view as B
HERE=Path(__file__).resolve().parent
SOURCES=list(dict.fromkeys(B.SOURCES+[Path(__file__),HERE/'attempt-inventory.sql']))
def build():return B.build()+b'\n'+(HERE/'attempt-inventory.sql').read_bytes()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'controller-attempt-inventory.sql'
    if a.check:assert target.read_bytes()==build()
    else:target.write_bytes(build())
