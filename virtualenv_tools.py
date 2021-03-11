#!/usr/bin/env python
"""
    move-virtualenv
    ~~~~~~~~~~~~~~~

    A helper script that moves virtualenvs to a new location.

    It only supports POSIX based virtualenvs and at the moment.

    :copyright: (c) 2012 by Fireteam Ltd.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import print_function

import argparse
import collections
import marshal
import os
import re
import shutil
import sys
from pathlib import Path
from types import CodeType

IS_WINDOWS = os.name == "nt"
BIN_DIR = "Scripts" if IS_WINDOWS else "bin"

ACTIVATION_SCRIPTS = [
    'activate',
    'activate.csh',
    'activate.fish',
    'activate.xsh',
    'activate.bat',
    'Activate.ps1',
    'activate.ps1',
    'activate_this.py'
]
matcher = re.compile(r'^((?:python)*\d*\.*\d*(?:\.exe)*)$')
_activation_path_re = re.compile(
    r'^(?:set -gx |setenv |set \"|)VIRTUAL_ENV[ =][\'\"]*(.*?)[\'\"]*\s*$'
)
VERBOSE = False
MAGIC_LENGTH = 4 + 4  # magic length + 4 byte timestamp
# In python3.3, a 4 byte "size" hint was added to pyc files
if sys.version_info >= (3, 3):  # pragma: no cover (PY33+)
    MAGIC_LENGTH += 4
# PEP 552 (implemented in python 3.7) extends this by another word
if sys.version_info >= (3, 7):  # pragma: no cover (PY37+)
    MAGIC_LENGTH += 4


def debug(msg):
    if VERBOSE:
        print(msg)


def _get_realpath(path):
    """Return real path without symlinks."""
    if os.path.exists(path):
        return str(Path(path).resolve())
    return path


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


def update_script(script_filename, new_path):
    """Updates shebang lines for actual scripts."""
    filesystem_encoding = sys.getfilesystemencoding()
    new_path = new_path.encode(filesystem_encoding)

    with open(script_filename, 'rb') as f:
        if f.read(2) != (b'MZ' if IS_WINDOWS else b'#!'):
            return
        f.seek(0)
        lines = list(f)

    found_shebang = False
    for line_i, line in enumerate(lines):

        shebang_offset = line.find(b'#!')
        if shebang_offset == -1:
            continue

        args = lines[line_i][shebang_offset + 2:].strip().split()
        if not args:
            continue

        if not os.path.isabs(args[0]):
            continue

        bin_name = Path(args[0].decode(filesystem_encoding)).name
        if not matcher.match(bin_name):
            continue

        new_bin = os.path.join(new_path, bin_name.encode(filesystem_encoding))

        if args[0] == new_bin:
            continue

        line_offset = line_i
        args_offset = shebang_offset + 2
        found_shebang = True
        break

    if not found_shebang:
        return

    args[0] = new_bin
    lines[line_offset] = lines[line_offset][:args_offset] + b" ".join(args) + b"\n"
    debug('S %s' % script_filename)
    with open(script_filename, 'wb') as f:
        f.writelines(lines)


def update_scripts(bin_dir, new_path):
    """Updates all scripts in the bin folder."""
    for fname in os.listdir(bin_dir):
        path = os.path.join(bin_dir, fname)
        if fname in ACTIVATION_SCRIPTS:
            update_activation_script(path, new_path)
        elif os.path.isfile(path):
            update_script(path, new_path)


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
            return CodeType(
                code.co_argcount, code.co_nlocals, code.co_stacksize,
                code.co_flags, code.co_code, tuple(consts), code.co_names,
                code.co_varnames, filename, code.co_name, code.co_firstlineno,
                code.co_lnotab, code.co_freevars, code.co_cellvars,
            )
        elif sys.version_info < (3, 8):  # pragma: no cover (<py38)
            return CodeType(
                code.co_argcount, code.co_kwonlyargcount, code.co_nlocals,
                code.co_stacksize, code.co_flags, code.co_code, tuple(consts),
                code.co_names, code.co_varnames, filename, code.co_name,
                code.co_firstlineno, code.co_lnotab, code.co_freevars,
                code.co_cellvars,
            )
        else:  # pragma: no cover (py38+)
            return code.replace(co_consts=tuple(consts), co_filename=filename)

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


def update_pycs(lib_dir, new_path):
    """Walks over all pyc files and updates their paths."""
    def get_new_path(filename):
        filename = Path(os.path.normpath(filename)).name
        return os.path.join(new_path, filename)

    pycs = Path(lib_dir).glob('**/*.pyc')
    pyos = Path(lib_dir).glob('**/*.pyo')
    for pyc in [*pycs, *pyos]:
        local_path = get_new_path(pyc)
        update_pyc(pyc, local_path)


def _update_pth_file(pth_filename, orig_path, is_pypy):
    with open(pth_filename) as f:
        lines = f.readlines()
    changed = False
    for i, line in enumerate(lines):
        val = line.strip()
        if val.startswith('import ') or not os.path.isabs(val):
            continue
        changed = True
        relto_original = os.path.relpath(val, orig_path)

        if is_pypy:  # pragma: no cover (pypy only)
            rel = '..'  # venv/site-packages
        elif IS_WINDOWS:  # pragma: no cover (Windows only)
            rel = '../..'  # venv/Lib/site-packages
        else:
            rel = '../../..'  # venv/lib/pythonX.X/site-packages

        relto_pth = os.path.join(rel, relto_original)
        lines[i] = '{}\n'.format(relto_pth)
    if changed:
        with open(pth_filename, 'w') as f:
            f.write(''.join(lines))
        debug('P {}'.format(pth_filename))


def update_pth_files(site_packages, orig_path, is_pypy):
    """Converts /full/paths in pth files to relative relocatable paths."""
    for filename in os.listdir(site_packages):
        filename = os.path.join(site_packages, filename)
        if filename.endswith(('.pth', '.egg-link')) and os.path.isfile(filename):
            _update_pth_file(filename, orig_path, is_pypy)


def update_pyvenv_cfg(pyvenv_cfg, new_path):
    with open(pyvenv_cfg) as f:
        lines = list(f)

    changed = False
    for line_i, line in enumerate(lines):  # pragma: no cover (covered by test_move_with_pyvencfg)
        key, path = line.split('=')
        if key.strip() != 'home':
            continue

        lines[line_i] = 'home = ' + new_path + '\n'
        changed = True
        break

    if not changed:  # pragma: no cover (covered by test_move_with_pyvencfg)
        return

    if path.strip() == new_path:
        return

    with open(pyvenv_cfg, 'w') as f:
        f.writelines(lines)
    debug('C {}'.format(pyvenv_cfg))


def remove_local(base):
    """On some systems virtualenv seems to have something like a local
    directory with symlinks.  This directory is safe to remove in modern
    versions of virtualenv.  Delete it.
    """
    local_dir = os.path.join(base, 'local')
    if os.path.exists(local_dir):  # pragma: no cover (not all systems)
        debug('D {}'.format(local_dir))
        shutil.rmtree(local_dir)


def update_paths(venv, base_python_dir=None):
    """Updates all paths in a virtualenv to a new one."""
    for lib_dir in [venv.bin_dir, *venv.lib_dirs]:
        update_pycs(lib_dir, venv.path)
    update_pth_files(venv.site_packages, venv.orig_path, venv.is_pypy)
    if base_python_dir:  # pragma: no cover (covered by test_move_with_pyvencfg)
        update_pyvenv_cfg(venv.pyvenv_cfg_file, base_python_dir)
    remove_local(venv.path)
    update_scripts(venv.bin_dir, venv.path)


def get_orig_path(venv_path):
    """This helps us know whether someone has tried to relocate the
    virtualenv
    """
    activate_path = os.path.join(venv_path, f'{BIN_DIR}/activate')

    with open(activate_path) as activate:
        for line in activate:
            # virtualenv 20 changes the position
            for possible in ('VIRTUAL_ENV="', "VIRTUAL_ENV='"):
                if line.startswith(possible):
                    return line.split(possible[-1], 2)[1]
        else:
            raise AssertionError(
                'Could not find VIRTUAL_ENV= in activation script: %s' %
                activate_path
            )


class NotAVirtualenvError(OSError):
    def __init__(self, *args):
        self.args = args

    def __str__(self):
        return '{} is not a virtualenv: not a {}: {}'.format(*self.args)


Virtualenv = collections.namedtuple(
    'Virtualenv', (
        'path',
        'bin_dir',
        'lib_dirs',
        'site_packages',
        'orig_path',
        'is_pypy',
        'pyvenv_cfg_file',
    ),
)


def _get_virtualenv_state(path, new_path=None):
    workon_home = os.getenv("WORKON_HOME")
    if workon_home is not None:
        env_path = os.path.join(workon_home, path)
        if os.path.exists(env_path):  # pragma: no cover
            path = env_path
    is_pypy = os.path.isdir(os.path.join(path, 'lib_pypy'))
    bin_dir = os.path.join(path, BIN_DIR)
    base_lib_dir = os.path.join(path, 'lib-python' if is_pypy else 'lib')
    activate_file = os.path.join(bin_dir, 'activate')
    pyvenv_cfg_file = os.path.join(path, 'pyvenv.cfg')

    for dir_path in (bin_dir, base_lib_dir):
        if not os.path.isdir(dir_path):
            raise NotAVirtualenvError(path, 'directory', dir_path)
    if not os.path.isfile(activate_file):
        raise NotAVirtualenvError(path, 'file', activate_file)

    if IS_WINDOWS:  # pragma: no cover (Windows only)
        lib_dir = base_lib_dir
    else:
        lib_dirs = [
            os.path.join(base_lib_dir, potential_lib_dir)
            for potential_lib_dir in os.listdir(base_lib_dir)
            if matcher.match(potential_lib_dir)
        ]
        if len(lib_dirs) != 1:
            raise NotAVirtualenvError(
                path,
                'directory',
                os.path.join(base_lib_dir, '#.#' if is_pypy else 'python#.#'),
            )
        lib_dir, = lib_dirs

    site_packages = os.path.join(path if is_pypy else lib_dir, 'site-packages')
    if not os.path.isdir(site_packages):
        raise NotAVirtualenvError(path, 'directory', site_packages)

    lib_dirs = [lib_dir]
    if is_pypy:  # pragma: no cover (pypy only)
        lib_dirs.append(os.path.join(path, 'lib_pypy'))
    return Virtualenv(
        path=new_path if new_path is not None else path,
        bin_dir=bin_dir,
        lib_dirs=lib_dirs,
        site_packages=site_packages,
        orig_path=_get_realpath(get_orig_path(path)),
        is_pypy=is_pypy,
        pyvenv_cfg_file=pyvenv_cfg_file,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Update paths in a virtualenv before/after moving it.',
        epilog=(
            'To be able to give a virtualenv name, WORKON_HOME variable must be set\n'
            'Before moving : %(prog)s -u new/path/of/venv old/path/of/venv\n'
            'Before moving : %(prog)s -u new/path/of/venv old_venv\n'
            'After moving and in the virtualenv : %(prog)s\n'
            'After moving : %(prog)s new_venv\n'
            'After moving : %(prog)s new/path/of/venv.\n'
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-u', '--update-path',
        help=(
            'Update the path for all required executables and helper files '
            'that are supported to the new python prefix.\n'
            'If omitted, path argument will be used.'
            'If a virtualenv name is given and "WORKON_HOME" is set, it will update'
            'this virtualenv otherwise fallback to path argument.'
        ),
    )
    parser.add_argument(
        '-b', '--base-python-dir',
        help=(
            'On Windows, a directory pointing to a valid Python installation.\n'
            'On *nux, a valid Python executable.\n'
            'The virtualenv will load standard libraries from here.'
            'This is needed to update pyvenv.cfg with a non default installation.'
            'If omitted, the default python will be used.'
        ),
    )
    parser.add_argument(
        '-f', '--force',
        action='store_true',
        help=(
            'Continue processing even if the original path is the same as the updated path.'
        ),
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show a listing of changes'
    )
    parser.add_argument(
        'path',
        nargs='?',
        help=(
            'Default to "."'
        )
    )
    args = parser.parse_args(argv)

    global VERBOSE
    VERBOSE = args.verbose

    update_path = args.update_path
    if update_path is not None:

        if not os.path.isabs(update_path):
            print('--update-path must be absolute: {}'.format(update_path))
            return 1

    base_python_dir = args.base_python_dir
    if base_python_dir is None or base_python_dir == 'auto':
        base_python_dir = sys.executable
    elif not os.path.isabs(base_python_dir):
        print('--base-python-dir must be absolute: {}'.format(base_python_dir))
        return 1

    # On Windows, executable is a copy and is not a symlink (not recommended)
    # On *nux, executable could be a symlink
    # On Windows, home is a directory, on *nux, home is an executable
    base_python_dir = os.path.dirname(base_python_dir) if IS_WINDOWS else base_python_dir

    if args.path is None:
        try:
            venv = _get_virtualenv_state(os.path.abspath('.'))
        except NotAVirtualenvError:
            parser.print_help()
            raise SystemExit
    else:
        path = _get_realpath(args.path)
        try:
            venv = _get_virtualenv_state(path=path, new_path=update_path)
        except NotAVirtualenvError as e:
            print(e)
            return 1

    if not args.force and venv.orig_path == venv.path:
        print('Already up-to-date: %s (%s)' % (venv.path, venv.orig_path))
        return 0

    update_paths(venv, base_python_dir)
    print('Updated: %s (%s -> %s)' % (venv.orig_path, venv.orig_path, venv.path))
    return 0


if __name__ == '__main__':
    exit(main())
