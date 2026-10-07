"""scripts/mercury_report.py saves the report with the newest local eval
summary in place of the server's pointer to evals/results/."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "mercury_report.py"
spec = importlib.util.spec_from_file_location("mercury_report", SCRIPT)
mercury_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mercury_report)

REPORT = (
    "# Mercury report since 2026-10-01\n\n## Escalations\n\nNo escalations.\n\n"
    "## Eval\n\nThe latest eval report is the newest file in evals/results/ in the public repo.\n\n"
    "## Spend\n\n- gemini: 0 of 500,000 tokens today\n"
)


def test_the_newest_eval_summary_replaces_the_pointer(tmp_path):
    (tmp_path / "2026-10-06T0410Z.md").write_text("| old |\n", encoding="utf-8")
    (tmp_path / "2026-10-07T0006Z.md").write_text("| ollama | 9 of 11 |\n", encoding="utf-8")

    text = mercury_report.with_latest_eval(REPORT, tmp_path)

    assert "From evals/results/2026-10-07T0006Z.md:" in text
    assert "| ollama | 9 of 11 |" in text
    assert "| old |" not in text
    assert "newest file in evals/results/" not in text
    assert text.endswith("- gemini: 0 of 500,000 tokens today\n")


def test_with_no_local_results_the_report_is_unchanged(tmp_path):
    assert mercury_report.with_latest_eval(REPORT, tmp_path / "missing") == REPORT
