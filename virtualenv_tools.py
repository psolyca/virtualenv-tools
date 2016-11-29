#!/usr/bin/env python
"""
    move-virtualenv
    ~~~~~~~~~~~~~~~

    A helper script that moves virtualenvs to a new location.

    It only supports POSIX based virtualenvs and Python 2 at the moment.

    :copyright: (c) 2012 by Fireteam Ltd.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import print_function

import marshal
import optparse
import os.path
import re
import shutil
import subprocess
import sys
from types import CodeType


ACTIVATION_SCRIPTS = [
    'activate',
    'activate.csh',
    'activate.fish'
]
_pybin_match = re.compile(r'^python\d+\.\d+$')
_activation_path_re = re.compile(
    r'^(?:set -gx |setenv |)VIRTUAL_ENV[ =]"(.*?)"\s*$',
)
VERBOSE = False
MAGIC_LENGTH = 4 + 4  # magic length + 4 byte timestamp
# In python3.3, a 4 byte "size" hint was added to pyc files
if sys.version_info >= (3, 3):  # pragma: no cover (PY33+)
    MAGIC_LENGTH += 4


def debug(msg):
    if VERBOSE:
        print(msg)


def update_activation_script(script_filename, new_path):
    """Updates the paths for the activate shell scripts."""
    with open(script_filename) as f:
        lines = list(f)

    def _handle_sub(match):
        text = match.group()
        start, end = match.span()
        g_start, g_end = match.span(1)
        return text[:(g_start - start)] + new_path + text[(g_end - end):]

    changed = False
    for idx, line in enumerate(lines):
        new_line = _activation_path_re.sub(_handle_sub, line)
        if line != new_line:
            lines[idx] = new_line
            changed = True

    if changed:
        debug('A %s' % script_filename)
        with open(script_filename, 'w') as f:
            f.writelines(lines)


def path_is_within(path, within):
    relpath = os.path.relpath(path, within)
    return not relpath.startswith('.')


def update_script(script_filename, old_path, new_path):
    """Updates shebang lines for actual scripts."""
    with open(script_filename, 'rb') as f:
        if f.read(2) != b'#!':
            return

    with open(script_filename) as f:
        lines = list(f)
    args = lines[0][2:].strip().split()
    if not args:
        return

    if path_is_within(args[0], old_path):
        new_bin = os.path.join(new_path, os.path.relpath(args[0], old_path))
    else:
        return
    if new_bin == args[0]:
        return

    args[0] = new_bin
    lines[0] = '#!%s\n' % ' '.join(args)
    debug('S %s' % script_filename)
    with open(script_filename, 'w') as f:
        f.writelines(lines)


def update_scripts(bin_dir, orig_path, new_path, activation=False):
    """Updates all scripts in the bin folder."""
    for fname in os.listdir(bin_dir):
        path = os.path.join(bin_dir, fname)
        if fname in ACTIVATION_SCRIPTS and activation:
            update_activation_script(path, new_path)
        elif os.path.isfile(path):
            update_script(path, orig_path, new_path)


def update_pyc(filename, new_path):
    """Updates the filenames stored in pyc files."""
    with open(filename, 'rb') as f:
        magic = f.read(MAGIC_LENGTH)
        try:
            code = marshal.load(f)
        except Exception:
            print('Error in %s' % filename)
            raise

    def _make_code(code, filename, consts):
        if sys.version_info[0] == 2:  # pragma: no cover (PY2)
            arglist = [
                code.co_argcount, code.co_nlocals, code.co_stacksize,
                code.co_flags, code.co_code, tuple(consts), code.co_names,
                code.co_varnames, filename, code.co_name, code.co_firstlineno,
                code.co_lnotab, code.co_freevars, code.co_cellvars,
            ]
        else:  # pragma: no cover (PY3)
            arglist = [
                code.co_argcount, code.co_kwonlyargcount, code.co_nlocals,
                code.co_stacksize, code.co_flags, code.co_code, tuple(consts),
                code.co_names, code.co_varnames, filename, code.co_name,
                code.co_firstlineno, code.co_lnotab, code.co_freevars,
                code.co_cellvars,
            ]
        return CodeType(*arglist)

    def _process(code):
        consts = []
        for const in code.co_consts:
            if type(const) is CodeType:
                const = _process(const)
            consts.append(const)
        if new_path != code.co_filename or consts != list(code.co_consts):
            code = _make_code(code, new_path, consts)
        return code

    new_code = _process(code)

    if new_code is not code:
        debug('B %s' % filename)
        with open(filename, 'wb') as f:
            f.write(magic)
            marshal.dump(new_code, f)


def update_pycs(lib_dir, new_path, lib_name):
    """Walks over all pyc files and updates their paths."""
    def get_new_path(filename):
        filename = os.path.normpath(filename)
        if filename.startswith(lib_dir.rstrip('/') + '/'):
            return os.path.join(new_path, filename[len(lib_dir) + 1:])

    for dirname, dirnames, filenames in os.walk(lib_dir):
        for filename in filenames:
            if filename.endswith(('.pyc', '.pyo')):
                filename = os.path.join(dirname, filename)
                local_path = get_new_path(filename)
                if local_path is not None:
                    update_pyc(filename, local_path)


def remove_local(base, new_path):
    """On some systems virtualenv seems to have something like a local
    directory with symlinks.  This directory is safe to remove in modern
    versions of virtualenv.  Delete it.
    """
    local_dir = os.path.join(base, 'local')
    if os.path.exists(local_dir):  # pragma: no cover (not all systems)
        debug('D {}'.format(local_dir))
        shutil.rmtree(local_dir)


def update_paths(base, new_path):
    """Updates all paths in a virtualenv to a new one."""
    if new_path == 'auto':
        new_path = os.path.abspath(base)
    if not os.path.isabs(new_path):
        print('error: %s is not an absolute path' % new_path)
        return False

    orig_path = get_original_path(base)
    if new_path == orig_path:
        print('Already up-to-date: %s (%s)' % (base, new_path))
        return True

    bin_dir = os.path.join(base, 'bin')
    base_lib_dir = os.path.join(base, 'lib')
    lib_dir = None
    lib_name = None

    if os.path.isdir(base_lib_dir):
        for folder in os.listdir(base_lib_dir):
            if _pybin_match.match(folder):
                lib_name = folder
                lib_dir = os.path.join(base_lib_dir, folder)
                break

    if lib_dir is None or not os.path.isdir(bin_dir) \
       or not os.path.isfile(os.path.join(bin_dir, 'python')):
        print('error: %s does not refer to a python installation' % base)
        return False

    update_scripts(bin_dir, orig_path, new_path)
    update_pycs(lib_dir, new_path, lib_name)
    remove_local(base, new_path)
    update_scripts(bin_dir, orig_path, new_path, activation=True)

    print('Updated: %s (%s -> %s)' % (base, orig_path, new_path))
    return True


def reinitialize_virtualenv(path):
    """Re-initializes a virtualenv."""
    lib_dir = os.path.join(path, 'lib')
    if not os.path.isdir(lib_dir):
        print('error: %s is not a virtualenv bin folder' % path)
        return False

    py_ver = None
    for filename in os.listdir(lib_dir):
        if _pybin_match.match(filename):
            py_ver = filename
            break

    if py_ver is None:
        print('error: could not detect python version of virtualenv %s' % path)
        return False

    sys_py_executable = subprocess.Popen(
        ['which', py_ver], stdout=subprocess.PIPE,
    ).communicate()[0].strip()

    if not sys_py_executable:
        print(
            'error: could not find system version for expected python '
            'version %s' % py_ver
        )
        return False

    lib_dir = os.path.join(path, 'lib', py_ver)

    args = ['virtualenv', '-p', sys_py_executable]
    if not os.path.isfile(os.path.join(
            lib_dir, 'no-global-site-packages.txt',
    )):
        args.append('--system-site-packages')

    for filename in os.listdir(lib_dir):
        if filename.startswith('distribute-') and \
           filename.endswith('.egg'):
            args.append('--distribute')

    new_env = {}
    for key, value in os.environ.items():
        if not key.startswith('VIRTUALENV_'):
            new_env[key] = value
    args.append(path)
    subprocess.Popen(args, env=new_env).wait()


def get_original_path(venv_path):
    """This helps us know whether someone has tried to relocate the
    virtualenv
    """
    activate_path = os.path.join(venv_path, 'bin/activate')

    with open(activate_path) as activate:
        for line in activate:
            if line.startswith('VIRTUAL_ENV="'):
                return line.split('"', 2)[1]
        else:
            raise SystemExit(
                'Could not find VIRTUAL_ENV=" in activation script: %s' %
                activate_path
            )


def main(argv=None):
    parser = optparse.OptionParser()
    parser.add_option('--reinitialize', action='store_true',
                      help='Updates the python installation '
                      'and reinitializes the virtualenv.')
    parser.add_option('--update-path', help='Update the path for all '
                      'required executables and helper files that are '
                      'supported to the new python prefix.  You can also set '
                      'this to "auto" for autodetection.')
    parser.add_option('--verbose', action='store_true',
                      help='show a listing of changes')
    options, paths = parser.parse_args(argv)
    global VERBOSE
    VERBOSE = options.verbose
    if not paths:
        paths = ['.']

    rv = 0

    if options.reinitialize:
        for path in paths:
            reinitialize_virtualenv(path)
    elif options.update_path:
        for path in paths:
            if not update_paths(path, options.update_path):
                rv = 1
    else:
        parser.parse_args(['--help'])
    return rv


if __name__ == '__main__':
    exit(main())
