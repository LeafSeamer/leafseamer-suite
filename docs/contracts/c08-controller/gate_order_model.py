"""最终出口的有限串行参考模型；无网络、数据库、设备或真实身份提供者。"""
from dataclasses import dataclass


class Rejected(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise Rejected(reason)


@dataclass(frozen=True)
class Frame:
    session: str
    seq: int
    kind: str
    key: str
    body: tuple
    serial: int


class Gate:
    """单设备、单当前会话。truth字段由合成可信上下文提供。"""
    def __init__(self, session='session.1'):
        self.session = session
        self.serial = 0
        self.storage = True
        self.protected = True
        self.ready = False
        self.controller_lease = 0
        self.resources_clear = False
        self.targets = {}
        self.acks = set()
        self.consumed = set()
        self.recovery = None
        self.revision = 0
        self.barrier = None
        self.wire = []
        self.sent = {}
        self.next_seq = 1
        self.worker_next = 1
        self.worker_live = True
        self.worker_open = False
        self.worker_barrier = None
        self.worker_revision = 0
        self.worker_lease = 0
        self.worker_token = None
        self.close_cache = {}
        self.permits = set()
        self.effects = []
        self.receipts = []

    def protect(self, target, attempt):
        require(attempt == self.targets.get(target, 0) + 1, 'attempt_successor')
        self.targets[target] = attempt
        self.serial += 1
        self.protected, self.ready, self.recovery, self.barrier = True, False, None, None

    def enqueue(self, kind, key, body):
        frame = Frame(self.session, self.next_seq, kind, key, tuple(body), self.serial)
        self.next_seq += 1
        self.wire.append(frame)
        self.sent[frame.seq] = frame
        return frame

    def close(self, target, attempt):
        key = (target, attempt)
        require(self.storage and self.protected, 'not_protected')
        require(self.targets.get(target) == attempt, 'stale_attempt')
        require(key not in self.acks or key in self.consumed, 'already_acked')
        return self.enqueue('close', f'{target}.{attempt}', key)

    def fail_storage(self):
        self.storage = False
        self.serial += 1
        self.protected, self.ready, self.barrier, self.recovery = True, False, None, None
        return self.enqueue('close', 'emergency.'+str(self.serial), ('emergency', self.serial))

    def recover(self, identity):
        require(self.storage and self.resources_clear, 'recovery_precondition')
        if self.recovery == identity and not self.protected:
            return
        require(self.protected, 'already_recovered')
        selected = set(self.targets.items())
        require(selected <= self.acks and not selected & self.consumed, 'fresh_close_required')
        self.consumed.update(selected)
        self.recovery, self.protected = identity, False
        self.serial += 1

    def fence(self):
        require(self.storage and not self.protected and self.recovery is not None, 'fence_precondition')
        self.revision += 1
        self.barrier = None
        self.ready = False
        return self.enqueue('fence', 'barrier.'+str(self.revision), (self.revision,))

    def plan_open(self, lease):
        require(self.storage and self.resources_clear and not self.protected and self.barrier is not None, 'open_precondition')
        return (self.session, self.serial, self.barrier, self.revision, lease, self.recovery)

    def open(self, plan, now=0):
        session, serial, barrier, revision, lease, recovery = plan
        require(self.storage and self.resources_clear and not self.protected, 'protected')
        require((session, serial, barrier, revision, recovery) ==
                (self.session, self.serial, self.barrier, self.revision, self.recovery), 'stale_open')
        require(barrier is not None and now < lease, 'expired')
        return self.enqueue('open', 'token.'+str(revision), (barrier, revision, lease))

    def dispatch(self, permit, now=0):
        require(self.storage and self.resources_clear and not self.protected and self.ready and now < self.controller_lease, 'not_ready')
        return self.enqueue('dispatch', permit, (self.revision, 'token.'+str(self.revision), now))

    def receive(self, frame, now=0):
        try:
            return self._receive(frame, now)
        except Rejected as error:
            if str(error) in ('wrong_session', 'sequence_gap', 'close_content_conflict', 'unknown_kind'):
                self.lose_cache()
            raise

    def lose_cache(self):
        self.worker_live, self.worker_open, self.worker_barrier = False, False, None

    def _receive(self, frame, now):
        require(self.worker_live, 'session_closed')
        if self.worker_open and now >= self.worker_lease:
            self.worker_open, self.worker_barrier = False, None
        require(frame.session == self.session, 'wrong_session')
        require(frame.seq == self.worker_next, 'sequence_gap')
        self.worker_next += 1
        if frame.kind == 'close':
            if frame.key in self.close_cache:
                require(self.close_cache[frame.key] == frame.body, 'close_content_conflict')
            else:
                self.worker_open, self.worker_barrier = False, None
                self.close_cache[frame.key] = frame.body
        elif frame.kind == 'fence':
            require(frame.body[0] > self.worker_revision, 'stale_fence')
            self.worker_revision = frame.body[0]
            self.worker_open = False
            self.worker_barrier = frame.key
        elif frame.kind == 'open':
            barrier, revision, lease = frame.body
            require(barrier == self.worker_barrier and revision == self.worker_revision, 'worker_open_binding')
            require(now < lease, 'expired')
            self.worker_open, self.worker_lease, self.worker_token = True, lease, frame.key
        elif frame.kind == 'dispatch':
            revision, token, _ = frame.body
            require(frame.key not in self.permits, 'permit_consumed')
            require(self.worker_open and now < self.worker_lease, 'worker_closed')
            require((revision, token) == (self.worker_revision, self.worker_token), 'permit_binding')
            self.permits.add(frame.key)
            self.effects.append(frame.key)
        else:
            raise Rejected('unknown_kind')
        self.receipts.append(frame)
        return frame

    def deliver(self, now=0):
        require(bool(self.wire), 'empty_wire')
        return self.receive(self.wire.pop(0), now)

    def store_ack(self, frame, now=0):
        require(self.storage, 'storage_failed')
        require(frame.session == self.session and self.sent.get(frame.seq) == frame, 'ack_origin')
        require(frame in self.receipts, 'no_worker_receipt')
        if frame.kind == 'close':
            self.acks.add(frame.body)
        elif frame.kind == 'fence':
            require(frame.serial == self.serial and not self.protected and frame.body == (self.revision,), 'stale_ack')
            self.barrier = frame.key
        elif frame.kind == 'open':
            require(frame.serial == self.serial and not self.protected and frame.body[:2] ==
                    (self.barrier, self.revision), 'stale_ack')
            require(self.resources_clear and now < frame.body[2], 'open_ack_precondition')
            self.ready = True
            self.controller_lease = frame.body[2]

    def restart(self, session):
        require(session != self.session, 'session_reuse')
        # 抽象前提：监督器已证明旧进程和通道退役；真实退出证明不由此模型产生。
        self.__init__(session)
