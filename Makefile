COMPOSE ?= docker compose
SERVICE := azul-ai-agent

.PHONY: up down stop start restart status logs build

up:
	$(COMPOSE) up --build -d $(SERVICE)

down:
	$(COMPOSE) down

stop:
	$(COMPOSE) stop $(SERVICE)

start:
	$(COMPOSE) start $(SERVICE)

restart:
	$(COMPOSE) restart $(SERVICE)

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f $(SERVICE)

build:
	$(COMPOSE) build $(SERVICE)
