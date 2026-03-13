#!/usr/bin/env python3
"""
Script para verificar la calidad del retrieval RAG.
Ejecuta el golden dataset y muestra métricas.

Uso:
    python -m src.scripts.verify_retrieval
    python -m src.scripts.verify_retrieval --query "¿Cuál es la garantía?"
    python -m src.scripts.verify_retrieval --golden ./tests/golden_dataset.json
"""
import asyncio
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from loguru import logger
from dotenv import load_dotenv

load_dotenv()


async def test_single_query(query: str, top_k: int = 5) -> None:
    """Prueba una query individual y muestra los resultados."""
    from src.db.database import init_db, close_db
    from src.rag.retriever import HybridRetriever

    db_pool = await init_db()
    retriever = HybridRetriever(db_pool)

    try:
        logger.info(f"Query: '{query}'")
        result = await retriever.retrieve(query, top_k=top_k)
        logger.info(f"Método: {result.method} | Latencia: {result.latency_ms:.0f}ms")
        logger.info(f"Chunks encontrados: {len(result.chunks)}")

        for i, chunk in enumerate(result.chunks, 1):
            doc_title = chunk.metadata.get("doc_title", chunk.doc_id)
            print(f"\n[{i}] Score: {chunk.score:.4f} | Doc: {doc_title} | Sección: {chunk.section}")
            print(f"     {chunk.content[:300]}{'...' if len(chunk.content) > 300 else ''}")
    finally:
        await close_db()


async def run_golden_dataset(golden_path: str) -> dict:
    """Ejecuta el golden dataset y devuelve métricas."""
    from src.db.database import init_db, close_db
    from src.rag.retriever import HybridRetriever
    from src.rag.guardrails import RAGGuardrails

    with open(golden_path) as f:
        golden = json.load(f)

    db_pool = await init_db()
    retriever = HybridRetriever(db_pool)
    guardrails = RAGGuardrails()

    results = []
    try:
        for case in golden.get("test_cases", []):
            query = case["question"]
            result = await retriever.retrieve(query)
            response = await guardrails.generate_response(
                query=query,
                chunks=result.chunks,
                conversation_history=[],
            )

            should_handoff = case.get("should_handoff", False)
            actual_handoff = response.action.value in ("handoff", "no_evidence")
            correct_routing = (actual_handoff == should_handoff)

            expected_contains = case.get("expected_answer_contains", [])
            answer_correct = not expected_contains or any(
                exp.lower() in response.response_text.lower()
                for exp in expected_contains
            )

            results.append({
                "question": query,
                "correct_routing": correct_routing,
                "answer_correct": answer_correct or should_handoff,
                "confidence": response.confidence,
                "action": response.action.value,
                "evidence_found": response.evidence_found,
            })

            status = "✓" if correct_routing and (answer_correct or should_handoff) else "✗"
            logger.info(
                f"  {status} '{query[:60]}' → {response.action.value} "
                f"(conf={response.confidence:.2f})"
            )
    finally:
        await close_db()

    # Calcular métricas
    total = len(results)
    correct = sum(1 for r in results if r["correct_routing"] and r["answer_correct"])
    handoffs = sum(1 for r in results if r["action"] in ("handoff", "no_evidence"))
    evidence = sum(1 for r in results if r["evidence_found"])

    metrics = {
        "total_cases": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total > 0 else 0,
        "handoff_rate": round(handoffs / total, 3) if total > 0 else 0,
        "evidence_rate": round(evidence / total, 3) if total > 0 else 0,
        "avg_confidence": round(
            sum(r["confidence"] for r in results) / total, 3
        ) if total > 0 else 0,
    }

    print("\n" + "=" * 60)
    print("RESULTADOS DEL GOLDEN DATASET")
    print("=" * 60)
    print(f"Total casos:     {metrics['total_cases']}")
    print(f"Correctos:       {metrics['correct']} ({metrics['accuracy']:.1%})")
    print(f"Handoff rate:    {metrics['handoff_rate']:.1%}")
    print(f"Evidence rate:   {metrics['evidence_rate']:.1%}")
    print(f"Avg confidence:  {metrics['avg_confidence']:.3f}")
    print("=" * 60)

    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verificación del RAG de Saxun")
    parser.add_argument("--query", "-q", help="Query individual a probar")
    parser.add_argument(
        "--golden", "-g",
        default="./src/tests/golden_dataset.json",
        help="Ruta al golden dataset JSON",
    )
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.query:
        asyncio.run(test_single_query(args.query, args.top_k))
    else:
        asyncio.run(run_golden_dataset(args.golden))
