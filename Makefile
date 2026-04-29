#################################################################################
# GLOBALS                                                                       #
#################################################################################

ifneq (,$(wildcard ./_environment.local))
    include _environment.local
    export
endif

current_dir := $(shell pwd)

#################################################################################
# COMMANDS                                                                      #
#################################################################################

.PHONY: help
help: ## Show all available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

##### QUARTO

.PHONY: render
render: ## Render Quarto site
	quarto render

.PHONY: render-file
render-file: ## Render one .qmd file + index. Usage: make render-file FILE=pages/lectures/intro.qmd
ifndef FILE
	$(error FILE is required. Example: make render-file FILE=pages/lectures/intro.qmd)
endif
	quarto render $(FILE)
	quarto render index.qmd

##### EXAM

.PHONY: create-exam
create-exam: ## Make exam tex
	export TEXINPUTS=${TEXINPUTS} && \
	cd ./docs/exam/tex && \
	xelatex -shell-escape main && \
	xelatex -shell-escape main && \
	xelatex -shell-escape main

.PHONY: clear-exam
clear-exam: ## Clear exam files
	cd ./docs/exam/tex && \
	find . -not -name "*.tex" -not -name "main.pdf" -not -name "exam.cls" -delete

.PHONY: exam
exam: create-exam clear-exam ## Make exam
