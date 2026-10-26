"""Operator entry with a whole-batch CLIENT process-group watchdog.

Default/preflight cannot read keys or create model requests. --execute still
requires the new, matching execution receipt. Termination is local only.
"""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
from binding import HERE,Halt,load_plan,verify_authorization

def supervise(command,timeout_s,logdir):
    logdir=Path(logdir);logdir.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    with (logdir/'CONTROLLER_STDOUT.log').open('x') as stdout,(logdir/'CONTROLLER_STDERR.log').open('x') as stderr:
        process=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True)
        timed_out=False
        try:code=process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out=True
            # The child owns this new process group; never target the IDE,
            # other project processes, or a host-wide process name.
            os.killpg(process.pid,signal.SIGTERM)
            try:code=process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);code=process.wait(timeout=2)
    result={'exit_code':code,'client_batch_timeout':timed_out,
            'client_controller_wall_s':time.monotonic()-start,'remote_cancellation_confirmed':False}
    (logdir/'CONTROLLER_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true');p.add_argument('--authorization');p.add_argument('--out')
    args=p.parse_args()
    try:
        plan=load_plan()
        if not args.execute:
            command=[sys.executable,str(HERE/'run.py'),'--preflight']
            if args.authorization:command+=['--authorization',args.authorization]
            return subprocess.call(command)
        verify_authorization(args.authorization,plan)
        if not args.out:raise Halt('OUTPUT_DIRECTORY_REQUIRED')
        out=Path(args.out).resolve()
        if out.exists() and any(out.iterdir()):raise Halt('OUTPUT_DIRECTORY_NOT_EMPTY')
        if (HERE/'REAL_BATCH_CLAIM.json').exists():raise Halt('REAL_BATCH_ALREADY_CLAIMED_NO_RESUME')
        # Controller logs are outside the result directory. Neither path may
        # already contain a prior attempt; no resume/append entry is supplied.
        logs=out.with_name(out.name+'_controller')
        if logs.exists():raise Halt('CONTROLLER_DIRECTORY_ALREADY_EXISTS')
        command=[sys.executable,str(HERE/'run.py'),'--execute','--authorization',str(Path(args.authorization).resolve()),'--out',str(out)]
        result=supervise(command,plan['batch_deadline_s'],logs)
        print(json.dumps(result,ensure_ascii=False))
        return 3 if result['client_batch_timeout'] else result['exit_code']
    except (Halt,FileExistsError) as exc:
        print(json.dumps({'status':'NOT_DISPATCHED','reason':str(exc),'real_model_requests':0},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
