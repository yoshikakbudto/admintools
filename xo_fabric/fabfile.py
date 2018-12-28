#!/usr/bin/env python

"""
this fabric supposed to speed things up when doing parallel rsync
but in our case it actually slowed things down.
But i decided to leave it for mems :) Maybe someday i'll make it work as expected.
"""
from fabric.api import *
from fabric.contrib import files, project
from fabric.context_managers import path
from fabric.utils import error
from joblib import Parallel, delayed
from subprocess import Popen, PIPE, STDOUT, check_output, call
import os
import random
import sys
import getpass
import shlex

PROJECT_NAME = 'emo'

BUILD_CFG = 'release'      # release or final-release
BUILD_PLATFORM = 'centos'
PRIVATE_BUILD = True
BUILD_LINUX_CLIENT = False
NINJA_ADD_ARGS = ''
REMOTE_DIR = ''

# remote builder settings
env.disable_known_hosts = True
env.key_filename = 'scripts/id_rsa_for_macbuilder'
if 'rsync_key' in env:
    env.key_filename = env.rsync_key

# assign centos builder for each windows builder to avoid centos-builder resources burnout.
#  if no environment var found, just pick random builder (of the 4 in total)
try:
    TC_AGENT_NAME=os.environ['TC_AGENT_NAME'].replace('.','-')
except KeyError:
    TC_AGENT_NAME='devserver{0}-agent1'.format(random.sample([1,2,3,4],1)[0])

# remote build machines per platform
BUILD_BOTS = {
    'linux': 'builduser@builder-ubuntu14-02.vm.targem.local',  # emo-ubuntu64
    'pc': 'builduser@192.168.20.3',
    'ps4': 'builduser@192.168.20.3',
    'vagrant_linux': 'vagrant@10.20.30.101',
    'centos': 'builduser@builder-centos7-{0}.targem.local'.format(TC_AGENT_NAME),
    'centos-pxo': 'builduser@build-server-lw-nl-01.pxo',
}

# isolate private builds from devservers's
BUILD_BOTS_PRIVATE = {
    #'centos': 'builduser@builder-centos7-private.targem.local',
    'centos': 'builduser@builder-centos7-02.vm.targem.local',
}

# used to find proper rsync, echo and other cygwin tools
CYGWIN_PATH = [
    r'd:\cygwin64\bin',
    r'd:\cygwin\bin',
    r'c:\cygwin\bin',
    r'c:\cygwin64\bin',
]

RSYNC_EXCLUDES = [
    'ios/',
    'android/',
    'mac/',
    'solaris/',
    '/bin/',
    'fabfile.py',
    'README',
    'README.*',
    'CHANGES',
    'HISTORY',
    'INSTALL',
    'doc/',
    'docs/',
    '/data',
    'temp/',
    '/ipch',
    '*.vsp',
    '/.*',
    '*.log',
    '*.md',
    '*.txt',
    '*.suo',
    '*.sdf',
    '*.pyc',
    '*.pdb',
    '*.VC.db',
    '.ninja_log',
    '.ninja_deps',]


# WARN: do not use --delete-excluded option with parallel directories sync
RSYNC_BASE_OPTS = '-zr --checksum'
RSYNC_EXTRA_OPTS = '--temp-dir=/dev/shm --timeout=180 --delete --no-perms --no-owner --no-group'

# Run in parallel RSYNC_PARALLEL_NUM rsyncs for subdirectories in each given path
#   even though having full paths in sync, the subsequental rsyncs 
#   wasting time when calculating and exchanging crc's. So paralleling helps alot here.
# The dict consists of subdirectory names and additional rsync options.
#   For code one should use --checksum rsync option - this will allow rsync 
#    to not touch files timestamps which could trigger re-build of them.
# Each pathname should start with '/', relative to checkout directory.
# Empty the dict to disable rsync parallel runs.
RSYNC_PARALLEL_PATHS = {}
#RSYNC_PARALLEL_PATHS = {'/code':'',
#                        '/middleware':''}
RSYNC_PARALLEL_NUM = 4

# will be generated out of RSYNC_EXCLUDES and platform-specific lists
#   for use with Popen-like system calls
RSYNC_GENERATED_EXCLUDES_CMDARGS = ''

# path to Visual Studio devenv on a remote machine
PC_PATH_TO_DEVENV = r'/cygdrive/c/Program Files (x86)/Microsoft Visual Studio 12.0/Common7/Tools/../IDE/devenv.com'


def fix_rsync_search_path():
    """Add Cygwin search path since Fabric is buggy and can't properly modify paths on Windows"""
    if sys.platform.startswith('win'):
        os.environ['PATH'] = ";".join(CYGWIN_PATH) + ';' + os.environ['PATH']


def generate_rsync_excludes():    
    """Generate  rsync excludes file."""
    global RSYNC_EXCLUDES
    global RSYNC_GENERATED_EXCLUDES_CMDARGS

    linux_platforms = ['centos', 'ubuntu', 'vagrant_linux', 'centos-pxo', 'linux']
    if BUILD_PLATFORM in linux_platforms:
        RSYNC_EXCLUDES += (
            'windows/',
            'Windows/',
            '*.dll',
            '*.lib',
            '*.bat',
            '*.cmd',
            '*.exe',
            '*.vcxproj',
            '*.vcxproj.*',
            '*.sln',
        )
    RSYNC_GENERATED_EXCLUDES_CMDARGS = r' '.join(['--exclude "\'{0}\'"'.format(x) for x in RSYNC_EXCLUDES])

def is_true(arg):
    return str(arg).lower() in ['true', 'yes']


def get_remote_dir():
    """Form remote build directory path name."""

    build_slot = ''
    build_branch = ''
    project_dir = PROJECT_NAME

    if BUILD_CFG == 'final-release':
        project_dir += '_final_release'
    if PRIVATE_BUILD:
        project_dir += '_private_%s' % getpass.getuser()

    try:
        build_slot = os.environ['build_slot']
        if build_slot != '':
            project_dir += '_%s' % build_slot
    except KeyError:
        pass

    if build_slot == '':
        try:
            build_branch = os.environ['build_branch']
            if build_branch != '':
                project_dir += '_%s' % build_branch
        except KeyError:
            pass

    if BUILD_PLATFORM == 'vagrant_linux':
        return '/project/code/%s' % PROJECT_NAME
    else:
        return '~/projects/%s' % project_dir


def psync(src_root, subdirs, rsync_path_opts):
    """Run rsync in Parallel for each subdirectory.

       To parallel rsync we use a Popen call to xargs, because the multiprocessing - based modules
        is a way hard to implement on top of fabric. Who wanna be a Hero to refactor this to mp ?
    """
    rsync_opts = '{0} {1} {2} {3}'.format(RSYNC_BASE_OPTS,
                                          RSYNC_EXTRA_OPTS,
                                          rsync_path_opts,
                                          RSYNC_GENERATED_EXCLUDES_CMDARGS)
    
    # because we dont use project.rsync_project we have to iterate over env.hosts manually.
    for remote_host in env.hosts:
        cmd=('xargs -rn1 -P{pnum} -I% '
             'rsync {args} {base_dir}/% {host}:{remote_dir}/{base_dir}/').format(
                   pnum=RSYNC_PARALLEL_NUM,
                   args=rsync_opts,
                   base_dir=src_root,
                   host=remote_host,
                   remote_dir=REMOTE_DIR)

        p = Popen(shlex.split(cmd), stdout=PIPE, stdin=PIPE, stderr=PIPE)
        (p_stdout, p_stderr) = p.communicate(input=b'\n'.join(subdirs))
        if p_stderr:
            print(p_stderr.decode())


def copy_source_code(src_dir, dst_dir):
    """Sync local source code tree w/ a remote builder.

    Paralleling rsync helps to speed things up at checksums exchange stage
      and for 'heavy' directories transfer. Use with caution: the destination
      device should be parallel-I/O friendly.
    To parallel rsync subdirectories, list them in RSYNC_PARALLEL_PATHS global
    """
    ssh_opts=('-o BatchMode=yes '
              '-o StrictHostKeyChecking=no '
              '-o Compression=no '
              '-o UserKnownHostsFile=/dev/null '
              '-o LogLevel=error '
              '-o PreferredAuthentications=publickey')

    # this is for parallel rsync
    os.environ['RSYNC_RSH'] = 'ssh {0} -i {1}'.format(ssh_opts, env.key_filename)

    # strip trailing slashes if exist
    while src_dir.endswith('/') or src_dir.endswith('\\'):
        src_dir = src_dir[:len(src_dir)-1]

    # sync everything except paths for parallel sync
    with hide('stdout'):
        project.rsync_project(local_dir=src_dir, remote_dir=dst_dir,
                          exclude=RSYNC_EXCLUDES + [k for k in RSYNC_PARALLEL_PATHS.iterkeys()],
                          default_opts=RSYNC_BASE_OPTS,
                          delete=True,
                          ssh_opts=ssh_opts,
                          extra_opts=RSYNC_EXTRA_OPTS)

    # run parallel sync for each defined paths
    #  RSYNC_PARALLEL_PATHS elements should start with '/'
    for path, rsync_path_opts in RSYNC_PARALLEL_PATHS.iteritems():
        try:
            root, subdirs, files = next(os.walk(src_dir + path))
            # sync root subdirectory with its files (if ones exist) 
            #print "syncing {0}'s files: {1}".format(root, files)
            with hide('running'):
                project.rsync_project(local_dir=root+'/', remote_dir=REMOTE_DIR+'/'+root+'/',
                                    exclude=RSYNC_EXCLUDES + ['*/'],
                                    default_opts=RSYNC_BASE_OPTS,
                                    delete=True,
                                    ssh_opts=ssh_opts,
                                    extra_opts=RSYNC_EXTRA_OPTS + ' ' + rsync_path_opts)
            psync(root, subdirs, rsync_path_opts)

        except StopIteration:
            print("[warn] couldnt traverse into {0}".format(path))


def build_linux_client():
    ninja_cfg = 'game-finalrelease.linux.ninja' if BUILD_CFG == 'final-release' else 'game-release.linux.ninja'
    ninja_dir = REMOTE_DIR + '/ninja/gamelinux/'
    with cd(ninja_dir):
        run('ninja {0} -f {1}'.format(NINJA_ADD_ARGS, ninja_cfg), shell_escape=False, pty=False)


def build_linux_servers():
    ninja_dir = REMOTE_DIR + '/ninja/gamelinux/'
    ninja_configs = ('servicecontainer-release.linux.ninja',
                     'dedicatedserver-release.linux.ninja')
    run('g++ --version', shell_escape=False, pty=False)
    with cd(ninja_dir):
        for cfg in ninja_configs:
            run('ninja {0} -f {1}'.format(NINJA_ADD_ARGS, cfg),
                shell_escape=False, pty=False)


def build_linux_stressbot():
    ninja_dir = REMOTE_DIR + '/ninja/gamelinux/'
    with cd(ninja_dir):
        run('ninja {0} -f stressbot-release.linux.ninja'.format(NINJA_ADD_ARGS),
            shell_escape=False, pty=False)


def build_linux_stresstool():
    ninja_dir = REMOTE_DIR + '/ninja/tools/'
    with cd(ninja_dir):
        run('ninja {0} -f stresstool-release.linux.ninja'.format(NINJA_ADD_ARGS),
            shell_escape=False, pty=False)


def dump_symbols(args=""):
    # generate breakpad symbols
    with cd(REMOTE_DIR):
        if args == "":
            run('python scripts/dump_breakpad_symbols.py')
        else:
            run('python scripts/dump_breakpad_symbols.py ' + args)


def is_gnudebug_linked(binary_file, section_name='.gnu_debuglink'):
    """Check if binary file contains specified debug section"""
    with settings(warn_only=True):
        res = run("readelf -S {0} | grep -qF {1}".format(binary_file, section_name))
        return res.return_code == 0


def strip_client():
    run('strip %s/bin/linux/Crossout' % REMOTE_DIR)


def strip_servers():
    # we would like to save space in SVN and still retain capabilities to perf this stuff on production
    # so we copy those before stripping, and add a debuglink
    # they get packed into server images but not in SVN
    strip_filelist = (  'ServiceContainer',
                        'DedicatedServer')
    with cd('%s/bin/linux' % REMOTE_DIR):
        for f in strip_filelist:
            if not is_gnudebug_linked(f):
                run('mv {0} {0}.full &&'
                    'strip {0}.full -o {0} &&'
                    'objcopy --add-gnu-debuglink={0}.full {0}'.format(f))


def strip_stressbot():
    run('strip %s/bin/linux/StressBot' % REMOTE_DIR)


def build_linux():
    if BUILD_LINUX_CLIENT:
        build_linux_client()
    build_linux_servers()
    if not PRIVATE_BUILD:
        dump_symbols()
        if BUILD_LINUX_CLIENT:
            strip_client()
        strip_servers()


def build_centos():
    # we dont need centos client, I think
    build_linux_servers()
    if not PRIVATE_BUILD:
        dump_symbols("centos")
        strip_servers()
    else:
        # we don't need those for now
        strip_servers()
        # well it's usually broken, so let it rot
        # build_linux_stressbot()
        # strip_stressbot()


def build_centos_pxo():
    # build servers and stress tool, no stripping
    build_linux_servers()
    build_linux_stresstool()


def build_vagrant_linux():
    build_linux_client()
    build_linux_servers()


def build_pc():
    with cd(REMOTE_DIR), hide('stdout'):
        run('"%s" "Project.sln" /build "Game-Release|Win32"' % PC_PATH_TO_DEVENV)


def build_ps4():
    with cd(REMOTE_DIR), hide('stdout'):
        run('"%s" "Project.sln" /build "Game-Release|ORBIS"' % PC_PATH_TO_DEVENV)


def get_build_results():

    if BUILD_PLATFORM == 'centos':
        LOCAL_PATH = './bin/linux/centos/'
        if not os.path.exists(LOCAL_PATH):
            os.makedirs(LOCAL_PATH)

        with hide('warnings'):
            get(remote_path=REMOTE_DIR +
                '/bin/linux/DedicatedServer', local_path=LOCAL_PATH)
            get(remote_path=REMOTE_DIR +
                '/bin/linux/ServiceContainer', local_path=LOCAL_PATH)

            # bot executable, if built
            botApp = REMOTE_DIR + '/bin/linux/StressBot'
            if files.exists(botApp):
                get(remote_path=botApp, local_path=LOCAL_PATH)

    elif BUILD_PLATFORM == 'linux':
        with hide('warnings'):
            if BUILD_LINUX_CLIENT:
                get(remote_path=REMOTE_DIR + '/bin/linux/Crossout', local_path='./bin/linux/')
            get(remote_path=REMOTE_DIR +
                '/bin/linux/DedicatedServer', local_path='./bin/linux/')
            get(remote_path=REMOTE_DIR +
                '/bin/linux/ServiceContainer', local_path='./bin/linux/')

            # copy dbg exe as well (for debug purposes)
            dbg_exe = REMOTE_DIR + '/bin/linux/Crossout_dbg'
            if files.exists(dbg_exe):
                get(remote_path=dbg_exe, local_path='./bin/linux/')

    elif BUILD_PLATFORM == 'ps4':
        get(remote_path=REMOTE_DIR +
            '/bin/ps4/game.elf', local_path='./bin/ps4/')


def delete_build_dir():
    run('rm -fR ' + REMOTE_DIR)


def get_private_cpu_limits():
    """ return a tuple of threads num and a load avg cap for -j and -l ninja flags. """
    with hide('output'):
        c = run("getconf _NPROCESSORS_ONLN")
    c = int(c)
    return (c/2, c-2)

@task
def build(platform='centos', cfg='release', build_for='private', cleanup='yes', just_copy_souce_code='no', build_linux_client='no', egoistic='no'):
    global BUILD_PLATFORM
    global BUILD_CFG
    global BUILD_LOCAL
    global PRIVATE_BUILD
    global BUILD_LINUX_CLIENT
    global NINJA_ADD_ARGS
    global REMOTE_DIR

    BUILD_PLATFORM = platform.lower()
    if BUILD_PLATFORM not in BUILD_BOTS.keys():
        error('Invalid platform: %s' % platform)
    
    BUILD_CFG = cfg.lower()
    if BUILD_CFG not in ['release', 'final-release']:
        error('Invalid build type: %s' % cfg)

    PRIVATE_BUILD = False if build_for.lower() == 'global' else True
    BUILD_LINUX_CLIENT = is_true(build_linux_client)

    if BUILD_PLATFORM == 'pc' and not (PRIVATE_BUILD and BUILD_CFG == 'release'):
        error('Currently building PC remotely is experimental, you can build private release only')

    REMOTE_DIR = get_remote_dir()

    if not PRIVATE_BUILD:
        env.hosts = [BUILD_BOTS[BUILD_PLATFORM], ]
    else:        
        env.hosts = [BUILD_BOTS_PRIVATE[BUILD_PLATFORM], ]
        if not is_true(egoistic):
            res = execute(get_private_cpu_limits)
            (max_run_threads, loadavg_cut_threads) = res[BUILD_BOTS_PRIVATE[BUILD_PLATFORM]]
            NINJA_ADD_ARGS = '-j {0} -l {1}'.format(max_run_threads, loadavg_cut_threads)

    fix_rsync_search_path()

    generate_rsync_excludes()

    if is_true(just_copy_souce_code) and is_true(cleanup):
        execute(delete_build_dir)

    execute(copy_source_code, src_dir='.', dst_dir=REMOTE_DIR)

    if is_true(just_copy_souce_code):
        return

    if BUILD_PLATFORM == 'linux':
        execute(build_linux)
    elif BUILD_PLATFORM == 'pc':
        execute(build_pc)
    elif BUILD_PLATFORM == 'ps4':
        execute(build_ps4)
    elif BUILD_PLATFORM == 'vagrant_linux':
        execute(build_vagrant_linux)
    elif BUILD_PLATFORM == 'centos':
        execute(build_centos)
    elif BUILD_PLATFORM == 'centos-pxo':
        execute(build_centos_pxo)

    execute(get_build_results)

    if is_true(cleanup):
        execute(delete_build_dir)

if __name__ == "__main__":
    print("[warn] this supposed to be run via fab")
