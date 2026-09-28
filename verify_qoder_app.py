"""One read-only desktop Qoder check; prints only display-ready quota fields."""
import json
from pathlib import Path
import time

from providers import qoder_provider

BASE = Path(__file__).resolve().parent

if __name__ == "__main__":
    started = time.time()
    try:
        value = qoder_provider.fetch()
        report = {"success": True, "balance": value["balance"], "unit": value["unit"],
                  "subtitle": value["subtitle"], "details": value["details"]}
    except RuntimeError as exc:
        report = {"success": False, "error": str(exc)}
    report.update(checked_at=time.strftime("%Y-%m-%d %H:%M:%S"), read_only=True,
                  seconds=round(time.time() - started, 2))
    destination = BASE / "tests" / "qoder_app_verification.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
