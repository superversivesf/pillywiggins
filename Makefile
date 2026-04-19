.PHONY: setup onboard up down test clean

setup:
	pipx install -e .
	@echo ""
	@echo "Setup complete! Run 'pillywiggins onboard' to configure your agents."

onboard:
	pillywiggins onboard

up:
	docker compose up -d --build

down:
	docker compose down

test:
	python3 -m pytest tests/ -q

clean:
	pipx uninstall pillywiggins