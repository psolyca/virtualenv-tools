import collections
import pipes
import subprocess
import sys

import pytest

import virtualenv_tools


def auto_namedtuple(**kwargs):
    return collections.namedtuple('ns', tuple(kwargs))(**kwargs)


@pytest.yield_fixture
def venv(tmpdir):
    app_before = tmpdir.join('before').ensure_dir()
    app_before.join('mymodule.py').write(
        "if __name__ == '__main__':\n"
        "    print('ohai!')\n"
    )
    app_before.join('setup.py').write(
        'from setuptools import setup\n'
        'setup(name="mymodule", py_modules=["mymodule"])\n'
    )
    venv_before = app_before.join('venv')
    app_after = tmpdir.join('after')
    venv_after = app_after.join('venv')

    cmd = (sys.executable, '-m', 'virtualenv', venv_before.strpath)
    subprocess.check_call(cmd)
    subprocess.check_call((
        venv_before.join('bin/pip').strpath,
        'install', '-e', app_before.strpath,
    ))
    yield auto_namedtuple(
        app_before=app_before, app_after=app_after,
        before=venv_before, after=venv_after,
    )


def run(before, after, args=()):
    ret = virtualenv_tools.main(
        (before.strpath, '--update-path={}'.format(after.strpath)) + args,
    )
    assert ret == 0


@pytest.mark.parametrize('helpargs', ((), ('--help',)))
def test_help(capsys, helpargs):
    with pytest.raises(SystemExit):
        virtualenv_tools.main(helpargs)
    out, err = capsys.readouterr()
    assert 'usage: ' in out + err


def test_already_up_to_date(venv, capsys):
    run(venv.before, venv.before)
    out, _ = capsys.readouterr()
    assert out == 'Already up-to-date: {0} ({0})\n'.format(venv.before)


def test_each_part_idempotent(tmpdir, venv, capsys):
    activate = venv.before.join('bin/activate')
    before_activate_contents = activate.read()
    run(venv.before, venv.after)
    capsys.readouterr()
    # Write the activate file to trick the logic into rerunning
    activate.write(before_activate_contents)
    run(venv.before, venv.after, args=('--verbose',))
    out, _ = capsys.readouterr()
    # Should only update our activate file:
    expected = 'A {0}\nUpdated: {1} ({1} -> {2})\n'.format(
        activate, venv.before, venv.after,
    )
    assert out == expected


def _assert_activated_sys_executable(path, py):
    exe = subprocess.check_output((
        'bash', '-c',
        ". {activate} && {py} -c 'import sys; print(sys.executable)'".format(
            activate=pipes.quote(path.join('bin/activate').strpath),
            py=py
        )
    )).decode('UTF-8').strip()
    assert exe == path.join('bin/{py}'.format(py=py)).strpath


def _assert_mymodule_output(path, py):
    out = subprocess.check_output(
        (path.join('bin/{py}'.format(py=py)).strpath, '-m', 'mymodule'),
        # Run from '/' to ensure we're not importing from .
        cwd='/',
    ).decode('UTF-8')
    assert out == 'ohai!\n'


def assert_virtualenv_state(path):
    _assert_activated_sys_executable(path, 'python')
    _assert_mymodule_output(path, 'python')


def test_move(venv, capsys):
    assert_virtualenv_state(venv.before)
    run(venv.before, venv.after)
    out, _ = capsys.readouterr()
    expected = 'Updated: {0} ({0} -> {1})\n'.format(venv.before, venv.after)
    assert out == expected
    venv.app_before.move(venv.app_after)
    assert_virtualenv_state(venv.after)


def test_move_with_auto(venv, capsys):
    venv.app_before.move(venv.app_after)
    ret = virtualenv_tools.main(('--update-path=auto', venv.after.strpath))
    out, _ = capsys.readouterr()
    expected = 'Updated: {1} ({0} -> {1})\n'.format(venv.before, venv.after)
    assert ret == 0
    assert out == expected
    assert_virtualenv_state(venv.after)


def test_bad_pyc(venv, capsys):
    libdir = 'lib/python{}.{}'.format(*sys.version_info[:2])
    bad_pyc = venv.before.join(libdir, 'bad.pyc')
    bad_pyc.write_binary(b'I am a very naughty pyc\n')
    # Retries on failures as well
    for _ in range(2):
        with pytest.raises(ValueError):
            run(venv.before, venv.after)
        out, _ = capsys.readouterr()
        assert out == 'Error in {}\n'.format(bad_pyc.strpath)


def test_dir_oddities(venv):
    bindir = venv.before.join('bin')
    # A directory existing in the bin dir
    bindir.join('im_a_directory').ensure_dir()
    # A broken symlink
    bindir.join('bad_symlink').mksymlinkto('/i/dont/exist')
    # A file with a shebang-looking start, but not actually
    bindir.join('not-an-exe').write('#!\nohai')
    run(venv.before, venv.after)


def test_verbose(venv, capsys):
    run(venv.before, venv.after, args=('--verbose',))
    out, _ = capsys.readouterr()
    # Lots of output
    assert len(out.splitlines()) > 50


def test_non_absolute_error(capsys):
    ret = virtualenv_tools.main(('--update-path', 'notabs'))
    out, _ = capsys.readouterr()
    assert ret == 1
    assert out == '--update-path must be absolute: notabs\n'


@pytest.yield_fixture
def fake_venv(tmpdir):
    tmpdir.join('bin').ensure_dir()
    tmpdir.join('lib/python2.7/site-packages').ensure_dir()
    tmpdir.join('bin/activate').write('VIRTUAL_ENV=/venv')
    yield tmpdir


def test_not_a_virtualenv_missing_bindir(fake_venv, capsys):
    fake_venv.join('bin').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a directory: {}\n'.format(
        fake_venv, fake_venv.join('bin'),
    )
    assert out == expected


def test_not_a_virtualenv_missing_activate_file(fake_venv, capsys):
    fake_venv.join('bin/activate').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a file: {}\n'.format(
        fake_venv, fake_venv.join('bin/activate'),
    )
    assert out == expected


def test_not_a_virtualenv_missing_versioned_lib_directory(fake_venv, capsys):
    fake_venv.join('lib/python2.7').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a directory: {}\n'.format(
        fake_venv, fake_venv.join('lib/python#.#'),
    )
    assert out == expected


def test_not_a_virtualenv_missing_site_packages(fake_venv, capsys):
    fake_venv.join('lib/python2.7/site-packages').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a directory: {}\n'.format(
        fake_venv, fake_venv.join('lib/python2.7/site-packages'),
    )
    assert out == expected

# -------- BEGIN Temp PyPy support Tests ------------
# After base functionality for pypy venv movement is reviewed
# these can be refactored in a way similar to how it was done in
# https://github.com/Yelp/virtualenv-tools/pull/11 to reduce duplication


skip_test_if_requires_pypy3 = pytest.mark.skipif(
    sys.version_info >= (3, 3),
    reason='pypy3 is not supported.'
)


def assert_virtualenv_state_pypy(path):
    _assert_activated_sys_executable(path, 'pypy')
    _assert_mymodule_output(path, 'pypy')


@pytest.yield_fixture
def venv_pypy(tmpdir):
    app_before = tmpdir.join('before').ensure_dir()
    app_before.join('mymodule.py').write(
        "if __name__ == '__main__':\n"
        "    print('ohai!')\n"
    )
    app_before.join('setup.py').write(
        'from setuptools import setup\n'
        'setup(name="mymodule", py_modules=["mymodule"])\n'
    )
    venv_before = app_before.join('venv')
    app_after = tmpdir.join('after')
    venv_after = app_after.join('venv')

    cmd = (sys.executable, '-m', 'virtualenv', venv_before.strpath,
           '-p', 'pypy' if sys.version_info < (3, 3) else 'pypy3')
    subprocess.check_call(cmd)
    subprocess.check_call((
        venv_before.join('bin/pip').strpath,
        'install', '-e', app_before.strpath,
    ))
    yield auto_namedtuple(
        app_before=app_before, app_after=app_after,
        before=venv_before, after=venv_after,
    )


@skip_test_if_requires_pypy3
def test_already_up_to_date_pypy(venv_pypy, capsys):
    run(venv_pypy.before, venv_pypy.before)
    out, _ = capsys.readouterr()
    assert out == 'Already up-to-date: {0} ({0})\n'.format(venv_pypy.before)


@skip_test_if_requires_pypy3
def test_each_part_idempotent_pypy(tmpdir, venv_pypy, capsys):
    activate = venv_pypy.before.join('bin/activate')
    before_activate_contents = activate.read()
    run(venv_pypy.before, venv_pypy.after)
    capsys.readouterr()
    # Write the activate file to trick the logic into rerunning
    activate.write(before_activate_contents)
    run(venv_pypy.before, venv_pypy.after, args=('--verbose',))
    out, _ = capsys.readouterr()
    # Should only update our activate file:
    expected = 'A {0}\nUpdated: {1} ({1} -> {2})\n'.format(
        activate, venv_pypy.before, venv_pypy.after,
    )
    assert out == expected


@skip_test_if_requires_pypy3
def test_move_pypy(venv_pypy, capsys):
    assert_virtualenv_state_pypy(venv_pypy.before)
    run(venv_pypy.before, venv_pypy.after)
    out, _ = capsys.readouterr()
    expected = 'Updated: {0} ({0} -> {1})\n'.format(
        venv_pypy.before,
        venv_pypy.after
    )
    assert out == expected
    venv_pypy.app_before.move(venv_pypy.app_after)
    assert_virtualenv_state_pypy(venv_pypy.after)


@skip_test_if_requires_pypy3
def test_move_with_auto_pypy(venv_pypy, capsys):
    venv_pypy.app_before.move(venv_pypy.app_after)
    ret = virtualenv_tools.main(
        ('--update-path=auto', venv_pypy.after.strpath)
    )
    out, _ = capsys.readouterr()
    expected = 'Updated: {1} ({0} -> {1})\n'.format(
        venv_pypy.before,
        venv_pypy.after
    )
    assert ret == 0
    assert out == expected
    assert_virtualenv_state_pypy(venv_pypy.after)


@skip_test_if_requires_pypy3
def test_bad_pyc_pypy(venv_pypy, capsys):
    libdir = 'lib-python/{}.{}'.format(*sys.version_info[:2])
    bad_pyc = venv_pypy.before.join(libdir, 'bad.pyc')
    bad_pyc.write_binary(b'I am a very naughty pyc\n')
    # Retries on failures as well
    for _ in range(2):
        with pytest.raises(ValueError):
            run(venv_pypy.before, venv_pypy.after)
        out, _ = capsys.readouterr()
        assert out == 'Error in {}\n'.format(bad_pyc.strpath)


@skip_test_if_requires_pypy3
def test_dir_oddities_pypy(venv_pypy):
    bindir = venv_pypy.before.join('bin')
    # A directory existing in the bin dir
    bindir.join('im_a_directory').ensure_dir()
    # A broken symlink
    bindir.join('bad_symlink').mksymlinkto('/i/dont/exist')
    # A file with a shebang-looking start, but not actually
    bindir.join('not-an-exe').write('#!\nohai')
    run(venv_pypy.before, venv_pypy.after)


@skip_test_if_requires_pypy3
def test_verbose_pypy(venv_pypy, capsys):
    run(venv_pypy.before, venv_pypy.after, args=('--verbose',))
    out, _ = capsys.readouterr()
    # Lots of output
    assert len(out.splitlines()) >= 30


@pytest.yield_fixture
def fake_venv_pypy(tmpdir):
    tmpdir.join('bin').ensure_dir()
    tmpdir.join('lib_pypy').ensure_dir()
    tmpdir.join('site-packages').ensure_dir()
    tmpdir.join('lib-python/2.7').ensure_dir()
    tmpdir.join('bin/activate').write('VIRTUAL_ENV=/venv')
    yield tmpdir


def test_not_a_virtualenv_missing_bindir_pypy(fake_venv_pypy, capsys):
    fake_venv_pypy.join('bin').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv_pypy.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a directory: {}\n'.format(
        fake_venv_pypy, fake_venv_pypy.join('bin'),
    )
    assert out == expected


def test_not_a_virtualenv_missing_activate_file_pypy(fake_venv_pypy, capsys):
    fake_venv_pypy.join('bin/activate').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv_pypy.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a file: {}\n'.format(
        fake_venv_pypy, fake_venv_pypy.join('bin/activate'),
    )
    assert out == expected


def test_not_a_virtualenv_missing_versioned_lib_directory_pypy(
    fake_venv_pypy,
    capsys
):
    fake_venv_pypy.join('lib-python/2.7').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv_pypy.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a directory: {}\n'.format(
        fake_venv_pypy, fake_venv_pypy.join('lib-python/#.#'),
    )
    assert out == expected


def test_not_a_virtualenv_missing_site_packages_pypy(fake_venv_pypy, capsys):
    fake_venv_pypy.join('site-packages').remove()
    ret = virtualenv_tools.main(('--update-path=auto', fake_venv_pypy.strpath))
    out, _ = capsys.readouterr()
    assert ret == 1
    expected = '{} is not a virtualenv: not a directory: {}\n'.format(
        fake_venv_pypy, fake_venv_pypy.join('site-packages'),
    )
    assert out == expected
