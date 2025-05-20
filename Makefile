.RECIPEPREFIX = >

.ONESHELL:
SHELL := bash

code := $(shell find ./main.py -iname \*.py)
line_length := 88

.PHONY: all test

.PHONY: lint
lint:
> black -l $(line_length) $(code)
> flake8 --max-line-length $(line_length) $(code)

test:
> echo Testing not implemented
