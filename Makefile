.PHONY: help install dev test lint docker-up docker-down ingest verify

# ── Ayuda ─────────────────────────────────────────────────────
help:
	@echo "Saxun Voice Assistant — Comandos disponibles:"
	@echo ""
	@echo "  install      Instalar dependencias"
	@echo "  dev          Arrancar servidor de desarrollo (con hot reload)"
	@echo "  test         Ejecutar tests"
	@echo "  lint         Ejecutar linter (ruff)"
	@echo "  docker-up    Levantar infraestructura (PostgreSQL + Redis + Langfuse)"
	@echo "  docker-down  Parar infraestructura"
	@echo "  migrate      Ejecutar migraciones de base de datos"
	@echo "  ingest       Ingestar documentos de rag-docs/"
	@echo "  verify       Verificar calidad del RAG (golden dataset)"

# ── Instalación ───────────────────────────────────────────────
install:
	pip install --upgrade pip
	pip install -r requirements.txt

# ── Desarrollo ────────────────────────────────────────────────
dev:
	uvicorn src.api.main:app \
		--host 0.0.0.0 \
		--port 8000 \
		--reload \
		--ws websockets \
		--log-level info

# ── Tests ─────────────────────────────────────────────────────
test:
	pytest src/tests/ -v --tb=short

test-security:
	pytest src/tests/test_security.py -v

test-rag:
	pytest src/tests/test_rag.py -v

# ── Linting ───────────────────────────────────────────────────
lint:
	ruff check src/
	ruff format --check src/

format:
	ruff format src/

# ── Docker ────────────────────────────────────────────────────
docker-up:
	docker compose up -d postgres redis
	@echo "✓ PostgreSQL y Redis arrancados"
	@echo "  Ejecuta 'make migrate' para inicializar la base de datos"

docker-up-all:
	docker compose up -d
	@echo "✓ Todos los servicios arrancados"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

# ── Base de datos ─────────────────────────────────────────────
migrate:
	@echo "Ejecutando migración inicial..."
	docker compose exec postgres psql -U saxun -d saxun_voice \
		-f /docker-entrypoint-initdb.d/001_initial.sql
	@echo "✓ Migración completada"

# ── RAG ───────────────────────────────────────────────────────
ingest:
	python -m src.scripts.ingest_docs --dir ./rag-docs
	@echo "✓ Documentos ingestados"

ingest-file:
	@read -p "Ruta del archivo: " FILE; \
	python -m src.scripts.ingest_docs --file $$FILE

verify:
	python -m src.scripts.verify_retrieval

verify-query:
	@read -p "Query: " QUERY; \
	python -m src.scripts.verify_retrieval --query "$$QUERY"

# ── Producción ────────────────────────────────────────────────
build:
	docker build -t saxun-voice-assistant:latest .

deploy-check:
	@echo "Verificando configuración para producción..."
	@test -n "$(OPENAI_API_KEY)" || (echo "ERROR: OPENAI_API_KEY no configurada" && exit 1)
	@test -n "$(TWILIO_ACCOUNT_SID)" || (echo "ERROR: TWILIO_ACCOUNT_SID no configurada" && exit 1)
	@test -n "$(DEEPGRAM_API_KEY)" || (echo "ERROR: DEEPGRAM_API_KEY no configurada" && exit 1)
	@echo "✓ Variables de entorno críticas presentes"
