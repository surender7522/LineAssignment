#! /bin/bash
echo 'Make sure to set appropriate url, userid, password, status, sleep time in main.py'
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3
$HOME/.poetry/bin/poetry install
echo 'Now run hypercorn main:app --bind "[::]:8000"'
$HOME/.poetry/bin/poetry shell
#hypercorn main:app --bind "[::]:8000"
