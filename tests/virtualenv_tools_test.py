import os.path
import pipes
import shutil
import subprocess
import sys

import pytest

import virtualenv_tools


def venv(path):
    subprocess.check_call((sys.executable, '-m', 'virtualenv', path))


def activated_sys_executable(path):
    return subprocess.check_output((
        'bash', '-c',
        ". {} && python -c 'import sys; print(sys.executable)'".format(
            pipes.quote(os.path.join(path, 'bin/activate')),
        )
    )).decode('UTF-8').strip()


@pytest.mark.parametrize('helpargs', ([], ['--help']))
def test_help(capsys, helpargs):
    with pytest.raises(SystemExit):
        virtualenv_tools.main(helpargs)
    out, _ = capsys.readouterr()
    assert 'Usage: ' in out


def test_already_up_to_date(tmpdir, capsys):
    path = tmpdir.join('venv').strpath
    venv(path)
    ret = virtualenv_tools.main(['--update-path={}'.format(path), path])
    out, _ = capsys.readouterr()
    assert ret == 0
    assert out == 'Already up-to-date: {} ({})\n'.format(path, path)


def test_move(tmpdir, capsys):
    before = tmpdir.join('before').strpath
    after = tmpdir.join('after').strpath
    venv(before)
    ret = virtualenv_tools.main(['--update-path={}'.format(after), before])
    out, _ = capsys.readouterr()
    assert ret == 0
    assert out == 'Updated: {} ({} -> {})\n'.format(before, before, after)
    shutil.move(before, after)
    exe = activated_sys_executable(after)
    assert exe == os.path.join(after, 'bin/python')


def test_bad_pyc(tmpdir, capsys):
    before_dir = tmpdir.join('before')
    before = before_dir.strpath
    after = tmpdir.join('after').strpath
    venv(before)
    libdir = 'lib/python{}.{}'.format(*sys.version_info[:2])
    bad_pyc = before_dir.join(libdir, 'bad.pyc')
    bad_pyc.write_binary(b'I am a very naughty pyc\n')
    # Retries on failures as well
    for _ in range(2):
        with pytest.raises(ValueError):
            virtualenv_tools.main(['--update-path={}'.format(after), before])
        out, _ = capsys.readouterr()
        assert out == 'Error in {}\n'.format(bad_pyc.strpath)


def test_dir_in_bin_ok(tmpdir):
    before_dir = tmpdir.join('before')
    before = before_dir.strpath
    after = tmpdir.join('after').strpath
    venv(before)
    before_dir.join('bin', 'im_a_directory').ensure_dir()
    # Successful
    ret = virtualenv_tools.main(['--update-path={}'.format(after), before])
    assert ret == 0


def test_broken_symlink_ok(tmpdir):
    before_dir = tmpdir.join('before')
    before = before_dir.strpath
    after = tmpdir.join('after').strpath
    venv(before)
    before_dir.join('bin', 'bad_symlink').mksymlinkto('/i/dont/exist')
    # Successful
    ret = virtualenv_tools.main(['--update-path={}'.format(after), before])
    assert ret == 0


def test_verbose(tmpdir, capsys):
    before = tmpdir.join('before').strpath
    after = tmpdir.join('after').strpath
    venv(before)
    ret = virtualenv_tools.main([
        '--update-path={}'.format(after), before,
        '--verbose',
    ])
    assert ret == 0
    out, _ = capsys.readouterr()
    # Lots of output
    assert len(out.splitlines()) > 50
