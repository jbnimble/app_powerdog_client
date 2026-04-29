#!/bin/bash

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
