ENV_NAME := Wii
PYTHON_VERSION := 3.11
VENV_DIR := venv

.PHONY: setup conda_setup venv_setup install clean

setup:
	@read -p "Use Conda or venv? select with (C/V): " choice; \
	if [ "$$choice" = "C" ] || [ "$$choice" = "c" ]; then \
		$(MAKE) conda_setup; \
	elif [ "$$choice" = "V" ] || [ "$$choice" = "v" ]; then \
		$(MAKE) venv_setup; \
	else \
		echo "Invalid choice. Please enter 'C' for Conda or 'V' for venv."; \
	fi

conda_setup:
	@echo "Setting up Conda environment: $(ENV_NAME)"
	conda create --name $(ENV_NAME) python=$(PYTHON_VERSION) -y
	conda run -n $(ENV_NAME) pip install -r requirements.txt
	@echo "Done. Activate with: conda activate $(ENV_NAME)"

venv_setup:
	@echo "Setting up Python virtual environment in $(VENV_DIR)"
	python3 -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install -r requirements.txt
	@echo "Done. Activate with: source $(VENV_DIR)/bin/activate"

clean:
	@read -p "Remove Conda env or venv? (C/V): " choice; \
	if [ "$$choice" = "C" ] || [ "$$choice" = "c" ]; then \
		conda remove --name $(ENV_NAME) --all -y; \
	elif [ "$$choice" = "V" ] || [ "$$choice" = "v" ]; then \
		rm -rf $(VENV_DIR); \
	else \
		echo "Invalid choice."; \
	fi