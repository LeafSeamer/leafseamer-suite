"""在既有完整摄取写集中加入独立封存行；查原和所有其他写入门槛不变。"""
import typed_seamer_model as T
I=T.I;P=T.P;raw=T.raw;need=T.need
def ingress_steps(db,event,ctx):
    writes=T.ingress_steps(db,event,ctx);out=[];seals=0
    for sql,args in writes:
        if sql=='UPDATE ingress_commit SET sealed=1 WHERE commit_id=?':
            need(len(args)==1,'seal_identity');out.append(I('ingress_commit_seal',commit_id=args[0]));seals+=1
        out.append((sql,args))
    need(seals==1,'one_ingress_commit');return out
def receive_event(db,event,ctx,fail_after=None):
    need(ctx['authorized'] and ctx['source_authenticated'],'source_authority');old=[]
    def builder():
        rows=P.rows(db,'SELECT * FROM ingress_inbox WHERE source_id=? AND(event_id=? OR source_sequence=?)',(event['source_id'],event['event_id'],event['source_sequence']))
        if rows:need(len(rows)==1 and rows[0]['content_body']==raw(event),'event_conflict');old.append(True);return []
        return ingress_steps(db,event,ctx)
    T.apply(db,builder,fail_after);return 'existing' if old else 'accepted'
