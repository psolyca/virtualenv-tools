import collections
import pipes
import subprocess
import sys

import pytest

import virtualenv_tools


@pytest.yield_fixture
def venv(tmpdir):
    before = tmpdir.join('before')
    after = tmpdir.join('after')
    cmd = (sys.executable, '-m', 'virtualenv', before.strpath)
    subprocess.check_call(cmd)
    yield collections.namedtuple('ns', ('before', 'after'))(before, after)


def run(before, after, args=()):
    ret = virtualenv_tools.main(
        (before.strpath, '--update-path={}'.format(after.strpath)) + args,
    )
    assert ret == 0


def activated_sys_executable(path):
    return subprocess.check_output((
        'bash', '-c',
        ". {} && python -c 'import sys; print(sys.executable)'".format(
            pipes.quote(path.join('bin/activate').strpath),
        )
    )).decode('UTF-8').strip()


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


def test_move(venv, capsys):
    run(venv.before, venv.after)
    out, _ = capsys.readouterr()
    expected = 'Updated: {0} ({0} -> {1})\n'.format(venv.before, venv.after)
    assert out == expected
    venv.before.move(venv.after)
    exe = activated_sys_executable(venv.after)
    assert exe == venv.after.join('bin/python').strpath


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
