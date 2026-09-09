"""Trusted child bootstrap. Untrusted code runs only after kernel restrictions."""
import ctypes
import errno
import json
import os
import resource
import sys


def restrict():
    if os.uname().machine!='x86_64':raise RuntimeError('Unsupported syscall architecture')
    if os.getuid()==0 or os.getgid()==0:raise RuntimeError('Must execute as an unprivileged uid/gid')
    libc=ctypes.CDLL(None,use_errno=True)
    sec=ctypes.CDLL('libseccomp.so.2',use_errno=True)
    if libc.syscall(444,0,0,1)<1:raise RuntimeError('Landlock unavailable')
    class Ruleset(ctypes.Structure):_fields_=[('handled_access_fs',ctypes.c_uint64)]
    class PathRule(ctypes.Structure):
        _pack_=1
        _fields_=[('allowed_access',ctypes.c_uint64),('parent_fd',ctypes.c_int32)]
    handled=(1<<13)-1
    rule=Ruleset(handled)
    fd=libc.syscall(444,ctypes.byref(rule),ctypes.sizeof(rule),0)
    if fd<0:raise OSError(ctypes.get_errno(),'landlock ruleset')
    read=(1<<2)|(1<<3)
    work=read  # Pure-function benchmark: no writable host directory or inode/space exhaustion.
    paths=[(sys.prefix,read),('/usr/lib',read),('/usr/lib64',read),(os.getcwd(),work),('/dev/null',(1<<1)|(1<<2)),('/dev/urandom',1<<2)]
    for path,access in paths:
        if not os.path.exists(path):continue
        parent=os.open(path,os.O_PATH|os.O_CLOEXEC)
        attr=PathRule(access,parent)
        result=libc.syscall(445,fd,1,ctypes.byref(attr),0)
        os.close(parent)
        if result:raise OSError(ctypes.get_errno(),'landlock rule')
    if libc.prctl(38,1,0,0,0):raise RuntimeError('no_new_privs failed')
    if libc.syscall(446,fd,0):raise OSError(ctypes.get_errno(),'landlock enforcement')
    os.close(fd)
    sec.seccomp_init.argtypes=[ctypes.c_uint32];sec.seccomp_init.restype=ctypes.c_void_p
    sec.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    sec.seccomp_load.argtypes=[ctypes.c_void_p];sec.seccomp_release.argtypes=[ctypes.c_void_p]
    sec.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];sec.seccomp_syscall_resolve_name.restype=ctypes.c_int
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(10,11))
    resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_NPROC,(1,1))
    ctx=sec.seccomp_init(0x00050000|errno.EPERM)  # default deny; unknown/new syscalls stay denied
    if not ctx:raise RuntimeError('seccomp init')
    allow=('read write readv writev pread64 pwrite64 close close_range fstat newfstatat stat lstat statx '
           'lseek mmap mprotect munmap mremap madvise brk '
           'rt_sigaction rt_sigprocmask rt_sigreturn sigaltstack '
           'open openat openat2 access faccessat faccessat2 getdents getdents64 '
           'readlink readlinkat getcwd fcntl dup dup2 dup3 '
           'getpid getppid gettid getuid geteuid getgid getegid '
           'clock_gettime clock_getres gettimeofday time nanosleep clock_nanosleep '
           'getrandom futex getrlimit getrusage sysinfo uname sched_getaffinity '
           'exit exit_group').split()
    for name in allow:
        number=sec.seccomp_syscall_resolve_name(name.encode())
        if number>=0 and sec.seccomp_rule_add(ctx,0x7fff0000,number,0):
            raise RuntimeError('seccomp allow rule '+name)
    if sec.seccomp_load(ctx):raise RuntimeError('seccomp load')
    sec.seccomp_release(ctx)



def main():
    payload=json.load(sys.stdin)
    try:
        restrict()
    except BaseException as exc:
        print(json.dumps(dict(sandbox_ready=False,error_type=type(exc).__name__,detail=str(exc))))
        return
    print('R3_SANDBOX_READY '+payload['nonce'],flush=True)
    result=dict(sandbox_ready=True,passed=False,nonce=payload['nonce'])
    try:
        # Same fresh global namespace for delivered code and frozen tests.
        scope={}
        exec(compile(payload['program'],'<candidate-and-tests>','exec'),scope)
        result['passed']=True
    except BaseException as exc:
        result['error_type']=type(exc).__name__
        result['error_detail']=str(exc)[:1000]
    print('\nR3_SANDBOX_RESULT '+json.dumps(result))

if __name__=='__main__':main()
