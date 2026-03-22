#!/usr/bin/env python3
"""
Runner de Testes - WebAuditBot SES
Executa todas as suites e gera relatório de resultados em JSON e texto.

Uso:
  python tests/run_tests.py
  python tests/run_tests.py --suite interface
  python tests/run_tests.py --suite import
  python tests/run_tests.py --verbose
"""

import argparse
import json
import sys
import time
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "tests" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class ColorOutput:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

    @classmethod
    def ok(cls, msg):    return f"{cls.GREEN}✔ {msg}{cls.RESET}"
    @classmethod
    def fail(cls, msg):  return f"{cls.RED}✘ {msg}{cls.RESET}"
    @classmethod
    def skip(cls, msg):  return f"{cls.YELLOW}⚠ {msg}{cls.RESET}"
    @classmethod
    def title(cls, msg): return f"{cls.BOLD}{cls.CYAN}{msg}{cls.RESET}"


class DetailedTestResult(unittest.TestResult):
    """Coleta resultados detalhados com tempo e mensagens de erro."""

    def __init__(self):
        super().__init__()
        self.test_details = []
        self._start_times = {}

    def startTest(self, test):
        super().startTest(test)
        self._start_times[test.id()] = time.monotonic()

    def _record(self, test, status, message=""):
        elapsed = (time.monotonic() - self._start_times.get(test.id(), time.monotonic())) * 1000
        name = test.id().split(".")[-1]
        doc = (test.shortDescription() or "").strip()
        self.test_details.append({
            "id": name,
            "description": doc,
            "status": status,
            "elapsed_ms": round(elapsed, 1),
            "message": message
        })

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "FAIL", self._exc_str(err))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "ERROR", self._exc_str(err))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "SKIP", reason)

    def _exc_str(self, err):
        return str(err[1]) if err and len(err) > 1 else ""


def run_suite(loader, suite_name, module_name, verbose=False) -> dict:
    """Executa uma suite e retorna dicionário de resultados."""
    print(ColorOutput.title(f"\n{'─'*55}"))
    print(ColorOutput.title(f"  Suite: {suite_name}"))
    print(ColorOutput.title(f"{'─'*55}"))

    suite = loader.loadTestsFromName(module_name)
    result = DetailedTestResult()
    start = time.monotonic()
    suite.run(result)
    total_ms = (time.monotonic() - start) * 1000

    # Imprime cada teste
    for detail in result.test_details:
        status = detail["status"]
        name = detail["id"]
        desc = detail["description"]
        ms = f"{detail['elapsed_ms']:.0f}ms"

        if status == "PASS":
            line = ColorOutput.ok(f"{name:<45} {ms:>8}")
        elif status == "FAIL":
            line = ColorOutput.fail(f"{name:<45} {ms:>8}")
            if detail["message"] and verbose:
                print(f"     {ColorOutput.RED}{detail['message'][:120]}{ColorOutput.RESET}")
        elif status == "ERROR":
            line = ColorOutput.fail(f"{name:<45} {ms:>8}  [ERRO]")
            if detail["message"] and verbose:
                print(f"     {ColorOutput.RED}{detail['message'][:120]}{ColorOutput.RESET}")
        else:
            line = ColorOutput.skip(f"{name:<45} {ms:>8}  [SKIP]")
        print(f"  {line}")

    # Imprime falhas detalhadas
    if result.failures or result.errors:
        print(f"\n  {ColorOutput.RED}FALHAS DETALHADAS:{ColorOutput.RESET}")
        for test, msg in result.failures + result.errors:
            print(f"\n  {ColorOutput.RED}▸ {test.id().split('.')[-1]}{ColorOutput.RESET}")
            for line in msg.strip().splitlines()[-6:]:
                print(f"    {line}")

    passed = len([d for d in result.test_details if d["status"] == "PASS"])
    failed = len(result.failures) + len(result.errors)
    total  = result.testsRun

    color = ColorOutput.GREEN if failed == 0 else ColorOutput.RED
    print(f"\n  {color}Resultado: {passed}/{total} passaram | "
          f"{failed} falha(s) | {total_ms:.0f}ms total{ColorOutput.RESET}")

    return {
        "suite": suite_name,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": len(result.skipped),
        "elapsed_ms": round(total_ms, 1),
        "tests": result.test_details
    }


def save_json_report(all_results: list, output_path: Path):
    """Salva relatório JSON completo."""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "WebAuditBot SES - Test Runner v1.0",
        "summary": {
            "total_suites": len(all_results),
            "total_tests": sum(r["total"] for r in all_results),
            "total_passed": sum(r["passed"] for r in all_results),
            "total_failed": sum(r["failed"] for r in all_results),
            "total_elapsed_ms": sum(r["elapsed_ms"] for r in all_results),
            "status": "PASS" if all(r["failed"] == 0 for r in all_results) else "FAIL"
        },
        "suites": all_results
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description="Runner de Testes WebAuditBot SES")
    parser.add_argument(
        "--suite", choices=["interface", "import", "all"], default="all",
        help="Suite a executar (padrão: all)"
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Exibe detalhes de falhas")
    args = parser.parse_args()

    print(ColorOutput.title(f"\n{'═'*55}"))
    print(ColorOutput.title("  WebAuditBot SES - Execução de Testes"))
    print(ColorOutput.title(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"))
    print(ColorOutput.title(f"{'═'*55}"))

    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # Mantém ordem de definição
    sys.path.insert(0, str(ROOT / "tests"))

    suites_to_run = []
    if args.suite in ("interface", "all"):
        suites_to_run.append(
            ("Erros de Interface e Instabilidade", "test_interface_instability")
        )
    if args.suite in ("import", "all"):
        suites_to_run.append(
            ("Rejeição de Importação de Arquivos", "test_import_rejection")
        )

    all_results = []
    for suite_name, module_name in suites_to_run:
        result = run_suite(loader, suite_name, module_name, verbose=args.verbose)
        all_results.append(result)

    # Resumo geral
    total_tests  = sum(r["total"] for r in all_results)
    total_passed = sum(r["passed"] for r in all_results)
    total_failed = sum(r["failed"] for r in all_results)
    overall_ok   = total_failed == 0

    print(ColorOutput.title(f"\n{'═'*55}"))
    print(ColorOutput.title("  RESUMO GERAL"))
    print(ColorOutput.title(f"{'═'*55}"))
    color = ColorOutput.GREEN if overall_ok else ColorOutput.RED
    status_str = "TODOS PASSARAM" if overall_ok else f"{total_failed} FALHA(S)"
    print(f"  {color}{ColorOutput.BOLD}{status_str}{ColorOutput.RESET}")
    print(f"  Testes: {total_passed}/{total_tests} passaram")
    for r in all_results:
        icon = "✔" if r["failed"] == 0 else "✘"
        c = ColorOutput.GREEN if r["failed"] == 0 else ColorOutput.RED
        print(f"  {c}{icon} {r['suite']}: {r['passed']}/{r['total']}{ColorOutput.RESET}")

    # Salva relatório JSON
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = RESULTS_DIR / f"test_report_{ts}.json"
    report = save_json_report(all_results, report_path)
    print(f"\n  Relatório salvo: {report_path}")
    print(ColorOutput.title(f"{'═'*55}\n"))

    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
