"""Read-only corrected-TEST final NAV postprocessor; never invokes an engine.

阶段 3 G02 决策：只读后处理无切换项，随训练后评估链保留 legacy。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACCOUNT_ROOT = PROJECT_ROOT / "artifacts" / "joint_e2e_gate_off" / "test_account_2026"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.account_engine_joint import postprocess_account


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ACCOUNT_ROOT,
                        help="test account directory (default: joint gate-off TEST account)")
    args = parser.parse_args()
    root = args.root.resolve()
    account = json.loads((root / "account.json").read_text(encoding="ascii"))
    raw = json.loads((root / "v6_raw" / "account.json").read_text(encoding="ascii"))
    trade_path = root / "trades.csv"
    trade_hash = hashlib.sha256(trade_path.read_bytes()).hexdigest()
    cutoff = account["final_liquidation_date"]
    result = postprocess_account(
        account, [account["initial"], raw["final"]], account["final"],
        account.get("locked_final", []), trade_hash, cutoff,
    )
    (root / "account_postprocessed.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
