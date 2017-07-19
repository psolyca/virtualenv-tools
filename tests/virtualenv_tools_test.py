import collections
import pipes
import subprocess
import sys

import pytest

import virtualenv_tools


def auto_namedtuple(**kwargs):
    return collections.namedtuple('ns', tuple(kwargs))(**kwargs)


def run(before, after, args=()):
    ret = virtualenv_tools.main(
        (before.strpath, '--update-path={}'.format(after.strpath)) + args,
    )
    assert ret == 0


def _assert_activated_sys_executable(path):
    exe = subprocess.check_output((
        'bash', '-c',
        ". {} && python -c 'import sys; print(sys.executable)'".format(
            pipes.quote(path.join('bin/activate').strpath)
        )
    )).decode('UTF-8').strip()
    assert exe == path.join('bin/python').strpath


def _assert_mymodule_output(path):
    out = subprocess.check_output(
        (path.join('bin/python').strpath, '-m', 'mymodule'),
        # Run from '/' to ensure we're not importing from .
        cwd='/',
    ).decode('UTF-8')
    assert out == 'ohai!\n'


def assert_virtualenv_state(path):
    _assert_activated_sys_executable(path)
    _assert_mymodule_output(path)


class TestVirtualEnvTools(object):

    lib_dir_pattern = 'lib/python{}.{}'
    site_packages_path = 'lib/python2.7/site-packages'
    expected_verbose_lines = 50

    @pytest.yield_fixture
    def venv(self, tmpdir):
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

    @pytest.mark.parametrize('helpargs', ((), ('--help',)))
    def test_help(self, capsys, helpargs):
        with pytest.raises(SystemExit):
            virtualenv_tools.main(helpargs)
        out, err = capsys.readouterr()
        assert 'usage: ' in out + err

    def test_already_up_to_date(self, venv, capsys):
        run(venv.before, venv.before)
        out, _ = capsys.readouterr()
        assert out == 'Already up-to-date: {0} ({0})\n'.format(venv.before)

    def test_each_part_idempotent(self, tmpdir, venv, capsys):
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

    def test_move(self, venv, capsys):
        assert_virtualenv_state(venv.before)
        run(venv.before, venv.after)
        out, _ = capsys.readouterr()
        expected = 'Updated: {0} ({0} -> {1})\n'.format(
            venv.before,
            venv.after
        )
        assert out == expected
        venv.app_before.move(venv.app_after)
        assert_virtualenv_state(venv.after)

    def test_move_with_auto(self, venv, capsys):
        venv.app_before.move(venv.app_after)
        ret = virtualenv_tools.main(('--update-path=auto', venv.after.strpath))
        out, _ = capsys.readouterr()
        expected = 'Updated: {1} ({0} -> {1})\n'.format(
            venv.before,
            venv.after
        )
        assert ret == 0
        assert out == expected
        assert_virtualenv_state(venv.after)

    def test_bad_pyc(self, venv, capsys):
        libdir = self.lib_dir_pattern.format(*sys.version_info[:2])
        bad_pyc = venv.before.join(libdir, 'bad.pyc')
        bad_pyc.write_binary(b'I am a very naughty pyc\n')
        # Retries on failures as well
        for _ in range(2):
            with pytest.raises(ValueError):
                run(venv.before, venv.after)
            out, _ = capsys.readouterr()
            assert out == 'Error in {}\n'.format(bad_pyc.strpath)

    def test_dir_oddities(self, venv):
        bindir = venv.before.join('bin')
        # A directory existing in the bin dir
        bindir.join('im_a_directory').ensure_dir()
        # A broken symlink
        bindir.join('bad_symlink').mksymlinkto('/i/dont/exist')
        # A file with a shebang-looking start, but not actually
        bindir.join('not-an-exe').write('#!\nohai')
        run(venv.before, venv.after)

    def test_verbose(self, venv, capsys):
        run(venv.before, venv.after, args=('--verbose',))
        out, _ = capsys.readouterr()
        # Lots of output
        assert len(out.splitlines()) >= self.expected_verbose_lines

    def test_non_absolute_error(self, capsys):
        ret = virtualenv_tools.main(('--update-path', 'notabs'))
        out, _ = capsys.readouterr()
        assert ret == 1
        assert out == '--update-path must be absolute: notabs\n'

    @pytest.yield_fixture
    def fake_venv(self, tmpdir):
        tmpdir.join('bin').ensure_dir()
        tmpdir.join('lib/python2.7/site-packages').ensure_dir()
        tmpdir.join('bin/activate').write('VIRTUAL_ENV=/venv')
        yield tmpdir

    def test_not_a_virtualenv_missing_bindir(self, fake_venv, capsys):
        fake_venv.join('bin').remove()
        ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
        out, _ = capsys.readouterr()
        assert ret == 1
        expected = '{} is not a virtualenv: not a directory: {}\n'.format(
            fake_venv, fake_venv.join('bin'),
        )
        assert out == expected

    def test_not_a_virtualenv_missing_activate_file(self, fake_venv, capsys):
        fake_venv.join('bin/activate').remove()
        ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
        out, _ = capsys.readouterr()
        assert ret == 1
        expected = '{} is not a virtualenv: not a file: {}\n'.format(
            fake_venv, fake_venv.join('bin/activate'),
        )
        assert out == expected

    def test_not_a_virtualenv_missing_versioned_lib_directory(
        self,
        fake_venv,
        capsys
    ):
        fake_venv.join(self.lib_dir_pattern.format(2, 7)).remove()
        ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
        out, _ = capsys.readouterr()
        assert ret == 1
        expected = '{} is not a virtualenv: not a directory: {}\n'.format(
            fake_venv, fake_venv.join(self.lib_dir_pattern.format('#', '#')),
        )
        assert out == expected

    def test_not_a_virtualenv_missing_site_packages(self, fake_venv, capsys):
        fake_venv.join(self.site_packages_path).remove()
        ret = virtualenv_tools.main(('--update-path=auto', fake_venv.strpath))
        out, _ = capsys.readouterr()
        assert ret == 1
        expected = '{} is not a virtualenv: not a directory: {}\n'.format(
            fake_venv, fake_venv.join(self.site_packages_path),
        )
        assert out == expected


# FIXME: We don't currently support (or test) pypy3
# We test py3 stuff when test interpreter is py3 and likewise we would test
# pypy3 under a py3 test interpreter, but we don't have it and don't care too
# much to fix it. This is because the pyc format changed in cpython3.3+.
# To work on pypy3 support change the skip condition to:
# `sys.version_info >= (3, 3) and shutil.which('pypy3') is None`
# this will allow the tests to proceed if pypy3 is available.
@pytest.mark.skipif(
    sys.version_info >= (3, 3),
    reason='We do not currently support (or test) pypy3.'
)
class TestVirtualEnvToolsPyPy(TestVirtualEnvTools):

    lib_dir_pattern = 'lib-python/{}.{}'
    site_packages_path = 'site-packages'
    expected_verbose_lines = 30

    @pytest.yield_fixture
    def venv(self, tmpdir):
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

    @pytest.yield_fixture
    def fake_venv(self, tmpdir):
        tmpdir.join('bin').ensure_dir()
        tmpdir.join('lib_pypy').ensure_dir()
        tmpdir.join('site-packages').ensure_dir()
        tmpdir.join('lib-python/2.7').ensure_dir()
        tmpdir.join('bin/activate').write('VIRTUAL_ENV=/venv')
        yield tmpdir
