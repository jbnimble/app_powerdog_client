#!/usr/bin/env bash

# ensure commands are run from the projects base directory in case the script is executed from somewhere else
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR
cd ..

echo 'script > delete virtualenv files'
rm -rf __pycache__
rm -rf .venv
rm -rf src/powerdog.egg-info
rm -rf src/powerdog/__pycache__

echo 'script > create virtualenv at .venv'
python3 -m venv .venv

echo 'script > activate virtualenv'
source .venv/bin/activate

echo 'script > upgrade pip'
.venv/bin/pip install --upgrade pip

echo 'script install module'
.venv/bin/pip install --requirement=requirements.txt --editable .
