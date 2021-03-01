#!/bin/sh

set -e

DRY_RUN_VALUE=$(grep DRY_RUN .env | xargs)
DRY_RUN_VALUE=${DRY_RUN_VALUE#*=}

poetry run fplmd DRY_RUN=DRY_RUN_VALUE