"""DAMJS executor wrapper (V0.2.1) — L2/L3/L4 + late-result isolation + budget guard.

DESIGN CONSTRAINTS
  * Stage_d_executor.py must keep its SHA unchanged (measured baseline: 64dea819…).
    This module never writes to it; the child process imports it read-only and
    monkeypatches only its per-node call hook at runtime.
  * "Timeout != cancellation": a Python thread blocked in urllib cannot be killed.
    Therefore the wrapper runs each execution in a **separate process** so the
    parent can truly terminate it at the deadline (SIGTERM then SIGKILL).

LAYERS
  L2  per-node call timeout  (socket-level timeout = W_eff)
  L3  global deadline        (process terminate at deadline - T_RESERVE)
  L4  degraded output        (completed nodes kept; unfinished slots -> UNKNOWN)
  P1a late-result isolation  (a result arriving after abort is written to the
                              quarantine log and never merged into the DAG)
  P1b budget protection      (calls / tokens / yuan checked before every call)

Zero-call by construction: transports are injected. The mock transport is used by
the stress test; the real one is only reachable after explicit authorization.
"""
from __future__ import annotations
import json, os, signal, threading, time, subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRESS_SCHEMA = 1


# ─────────────────────────── budget guard (P1b) ───────────────────────────
@dataclass
class BudgetGuard:
    calls_max: int = 400
    tokens_max: int = 1_400_000
    yuan_max: float = 2.50
    calls: int = 0
    tokens: int = 0
    yuan: float = 0.0
    log: List[dict] = field(default_factory=list)

    def precheck(self, est_tokens: int = 2500, est_yuan: float = 0.012) -> None:
        if self.calls + 1 > self.calls_max:
            raise RuntimeError(f'BUDGET calls {self.calls+1}>{self.calls_max}')
        if self.tokens + est_tokens > self.tokens_max:
            raise RuntimeError(f'BUDGET tokens {self.tokens+est_tokens}>{self.tokens_max}')
        if self.yuan + est_yuan > self.yuan_max:
            raise RuntimeError(f'BUDGET yuan {self.yuan+est_yuan:.4f}>{self.yuan_max}')

    def commit(self, tokens: int, yuan: float) -> None:
        self.calls += 1
        self.tokens += tokens
        self.yuan += yuan
        self.log.append(dict(calls=self.calls, tokens=self.tokens, yuan=round(self.yuan, 6)))

    def snapshot(self) -> dict:
        return dict(calls=self.calls, calls_max=self.calls_max,
                    tokens=self.tokens, tokens_max=self.tokens_max,
                    yuan=round(self.yuan, 6), yuan_max=self.yuan_max)


# ─────────────────── progress log (enables L4 degraded output) ───────────────────
class ProgressLog:
    """Append-only JSONL written by the child after every node start/finish."""

    def __init__(self, path: str, reset: bool = True):
        self.path = path
        if reset:                      # 只在创建者侧清空；读取方必须 reset=False
            open(self.path, 'w').close()

    def write(self, rec: dict) -> None:
        rec = dict(rec, schema=PROGRESS_SCHEMA, ts=time.time())
        with open(self.path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def read(self) -> List[dict]:
        out = []
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        return out

    def completed_outputs(self) -> Dict[str, str]:
        """Latest finished output per node (only nodes that truly finished)."""
        done: Dict[str, str] = {}
        for r in self.read():
            if r.get('ev') == 'node_end' and r.get('ok') and r.get('output') is not None:
                done[r['node']] = r['output']
        return done

    def aborted_nodes(self) -> List[str]:
        out = []
        for r in self.read():
            if r.get('ev') == 'node_abort':
                out.append(r['node'])
        return out


# ─────────────────────────── child-side guarded call ───────────────────────────
def _install_guarded_hooks(runner, progress: ProgressLog, guard: BudgetGuard,
                           cancel_path: str, real_transport: Callable):
    """Monkeypatch the frozen Runner instance's call path (no file edits)."""
    orig_call = runner.call

    def guarded_call(node, *a, **kw):
        if os.path.exists(cancel_path):
            progress.write(dict(ev='node_abort', node=node, reason='cancel_token'))
            raise RuntimeError('CANCELLED')
        progress.write(dict(ev='node_start', node=node))
        guard.precheck()
        t0 = time.time()
        try:
            out = orig_call(node, *a, **kw)
        except Exception as e:
            progress.write(dict(ev='node_end', node=node, ok=False, err=str(e)[:80],
                                wall=round(time.time() - t0, 2)))
            raise
        wall = round(time.time() - t0, 2)
        text = out if isinstance(out, str) else (out.get('text') if isinstance(out, dict) else str(out))
        progress.write(dict(ev='node_end', node=node, ok=True, output=text, wall=wall))
        guard.commit(tokens=len(text) // 2, yuan=0.003)
        return out

    runner.call = guarded_call
    return runner


# ─────────────────────────── main wrapper (L2/L3/L4) ───────────────────────────
class WatchdogResult(dict):
    pass


def run_isolated(*, arm: str, scenario: str, rep: int, deadline_s: float,
                 exec_cmd: List[str], progress_path: str, cancel_path: str,
                 reserve_s: float = 15.0, kill_grace_s: float = 2.0,
                 poll_s: float = 0.2, env: Optional[dict] = None,
                 log_path: Optional[str] = None) -> WatchdogResult:
    """Run one execution in a child process with a hard deadline.

    exec_cmd: command that starts the child runner (it must honour cancel_path
              by raising on its next call attempt).
    Returns a WatchdogResult with status COMPLETE or INCOMPLETE_DEADLINE_DEGRADED.
    """
    if os.path.exists(cancel_path):
        os.remove(cancel_path)
    t0 = time.time()
    # PIPE 死锁修复：子进程大量打印会写满 64KB 管道并阻塞，必须落盘而非 PIPE
    lp = log_path or (progress_path + '.out')
    _fh = open(lp, 'wb')
    proc = subprocess.Popen(exec_cmd, stdout=_fh, stderr=subprocess.STDOUT,
                            env=env, start_new_session=True)
    hard_deadline = deadline_s - reserve_s
    aborted = False
    while proc.poll() is None:
        if time.time() - t0 >= hard_deadline:
            aborted = True
            open(cancel_path, 'w').write('1')          # cooperative hint
            time.sleep(kill_grace_s)
            if proc.poll() is None:
                proc.terminate()                        # L3 hard stop
                time.sleep(kill_grace_s)
            if proc.poll() is None:
                proc.kill()
            break
        time.sleep(poll_s)
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        _fh.close()
    except Exception:
        pass
    err = b''
    try:
        with open(lp, 'rb') as fh:
            err = fh.read()[-4000:]
    except Exception:
        pass

    plog = ProgressLog(progress_path, reset=False)
    completed = plog.completed_outputs()
    aborted_nodes = plog.aborted_nodes()

    if aborted:
        # L4: degraded output — completed kept, everything else UNKNOWN
        return WatchdogResult(
            status='INCOMPLETE_DEADLINE_DEGRADED',
            arm=arm, scenario=scenario, rep=rep,
            elapsed=round(time.time() - t0, 1), deadline_s=deadline_s,
            completed_nodes=sorted(completed), aborted_nodes=sorted(set(aborted_nodes)),
            partial_outputs=completed,
            answer_status='DEGRADED',
            note='watchdog terminated child at deadline-reserve',
        )
    rc = proc.returncode
    return WatchdogResult(
        status='COMPLETE' if rc == 0 else f'CHILD_FAILED_rc{rc}',
        arm=arm, scenario=scenario, rep=rep,
        elapsed=round(time.time() - t0, 1), deadline_s=deadline_s,
        completed_nodes=sorted(completed), aborted_nodes=sorted(set(aborted_nodes)),
        partial_outputs=completed, answer_status='FULL',
        stderr=err.decode('utf-8', 'replace')[:400],
    )


# ─────────────────────── late-result quarantine (P1a) ───────────────────────
class Quarantine:
    """Holds results that arrive after an abort; never merged into the DAG."""

    def __init__(self, path: str, reset: bool = True):
        self.path = path
        if reset:                      # 只在创建者侧清空；读取方必须 reset=False
            open(self.path, 'w').close()

    def put(self, node: str, payload: dict, reason: str = 'aborted') -> None:
        rec = dict(node=node, reason=reason, payload=payload, ts=time.time())
        with open(self.path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def entries(self) -> List[dict]:
        out = []
        with open(self.path) as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
        return out


def merge_guarded(completed: Dict[str, str], late: List[dict]) -> Dict[str, str]:
    """Merge rule: abort-time completions only. Late results are rejected."""
    late_nodes = {e['node'] for e in late}
    return {k: v for k, v in completed.items() if k not in late_nodes}
