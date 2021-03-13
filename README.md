[![Build Status](https://travis-ci.com/psolyca/virtualenv-tools.svg?branch=master)](https://travis-ci.com/psolyca/virtualenv-tools)

virtualenv-tools-enhanced
-------------------------

virtualenv-tools-enhanced is a fork of [
virtualenv-tools3](https://github.com/Yelp/virtualenv-tools).


## virtualenv-tools-enhanced

This repository contains scripts I am using for my portable environment
used to develop with VSCodium.
As the environmnet is portable across different plateforms and computers,
I need a way to get Python and virtualenv working everywhere.

### Why not virtualenv --relocatable?

For starters: because it does not work. Relocatable is very
limited in what it does and it works at runtime instead of
making the whole thing actually move to the new location.  We
ran into a ton of issues with it and it is currently in the
process of being phased out.

### Why not virtualenv-tools3?

Because of some lack of Windows support.
Because...

### Why would I want to use it?

The main reason you want to use this is simplification.
No more long options, some more 'usefull' features.

### Help :

```
usage: virtualenv_tools.py [-h] [-m] [-u UPDATE_PATH] [-b BASE_PYTHON_DIR] [-f] [-c] [-v] [path]

Update paths in a virtualenv before/after moving it or a Python installation after moving it.

positional arguments:
  path                  Virtualenv folder, default to "."
                        Executable for main update.

optional arguments:
  -h, --help            show this help message and exit
  -m, --main            Update Python home after moving it.Portable Python is bad, not recommended and not supported.But why not?Windows only
  -u UPDATE_PATH, --update-path UPDATE_PATH
                        Update the path for all required executables and helper files that are supported to the new python prefix.
                        If omitted, path argument will be used.If a virtualenv name is given and "WORKON_HOME" is set, it will updatethis virtualenv otherwise fallback to path argument.
  -b BASE_PYTHON_DIR, --base-python-dir BASE_PYTHON_DIR
                        On Windows, a directory pointing to a valid Python installation.
                        On *nux, a valid Python executable.
                        The virtualenv will load standard libraries from here.This is needed to update pyvenv.cfg with a non default installation.If omitted, the default python will be used.
  -f, --force           Continue processing even if the original path is the same as the updated path.
  -c, --clean           Clean .pyc and .pyo files which are not the same version of the Python in the virtualenv or the main installation.
  -v, --verbose         Show a listing of changes

To be able to give a virtualenv name, WORKON_HOME variable must be set
Before moving : virtualenv_tools.py -u new/path/of/venv old/path/of/venv
Before moving : virtualenv_tools.py -u new/path/of/venv old_venv
After moving and in the virtualenv : virtualenv_tools.py
After moving : virtualenv_tools.py new_venv
After moving : virtualenv_tools.py new/path/of/venv.

For main installation, python as executable
virtualenv_tools.py -m python
```
