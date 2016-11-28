import pytest

import virtualenv_tools


@pytest.mark.parametrize('helpargs', ([], ['--help']))
def test_help(capsys, helpargs):
    with pytest.raises(SystemExit):
        virtualenv_tools.main(helpargs)
    out, _ = capsys.readouterr()
    assert 'Usage: ' in out
