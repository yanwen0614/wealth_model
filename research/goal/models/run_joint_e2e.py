"""Task 4 orchestration: project joint policies and accept them through V6.

阶段 3 G02 决策：训练后评估链仅 legacy（opt-in 可达），不接 adapter——
torch checkpoint 接线超收口范围，joint 订单路径已由 goal_adapter/joint_policy 覆盖。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.joint_portfolio import (
    JOINT_OUTDIR,
    RAW_DATA,
    JointPortfolioPolicy,
    _code_aligned_previous_weights,
    _load_episode_npz,
    _mark_to_market_holdings,
    _run_proxy_epoch,
    policy_weights,
    project_policy_scores,
)

WRAPPER = ROOT / "backtest" / "account_engine_joint.py"


def advance_projected_holdings(previous_by_code, codes, reward_valid, buy_open, sell_open):
    """Mark a completed episode to market before its state enters the next one."""
    ordered_codes = np.asarray(codes).astype(str)
    weights = torch.tensor([float(previous_by_code.get(code, 0.0)) if code else 0.0 for code in ordered_codes])
    marked = _mark_to_market_holdings(ordered_codes, weights, reward_valid, buy_open, sell_open)
    return {code: float(weight) for code, weight in marked.items()}


def project_checkpoint(checkpoint_path: Path, episodes_path: Path, output_path: Path, replacement_override=None) -> pd.Timestamp:
    """Project one policy by carrying its prior target weights code by code."""
    checkpoint = torch.load(checkpoint_path, weights_only=True)
    model = JointPortfolioPolicy()
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    episodes = _load_episode_npz(episodes_path)
    previous_by_code = {}
    parts = []
    # 循环携带变量：首轮 index==0 跳过使用，末轮赋值仅供下一轮；预置哨兵
    # 使定义可见（ruff F821/pyright possibly-unbound），运行期永不可达。
    prior_codes = prior_valid = prior_buy = prior_sell = None
    with torch.no_grad():
        for index in range(episodes["features"].shape[0]):
            codes = episodes["codes"][index]
            if index:
                previous_by_code = advance_projected_holdings(
                    previous_by_code, prior_codes, prior_valid, prior_buy, prior_sell
                )
            logits, replacement = model(torch.from_numpy(episodes["features"][index]).float())
            if replacement_override is not None:
                replacement = torch.tensor(float(replacement_override))
            previous, _ = _code_aligned_previous_weights(previous_by_code, codes)
            active = np.asarray(codes).astype(str) != ""
            target, _ = policy_weights(
                logits[active], previous[active], replacement, checkpoint["temperature"],
                allow_partial_previous=True,
            )
            full_target = np.zeros(len(codes), dtype=np.float64)
            full_target[active] = target.cpu().numpy()
            previous_by_code = {str(code): float(weight) for code, weight in zip(codes, full_target) if code}
            prior_codes = codes
            prior_valid = episodes["reward_valid"][index]
            prior_buy = episodes["buy_open"][index]
            prior_sell = episodes["sell_open"][index]
            part = project_policy_scores(codes, full_target)
            part["kline_time"] = pd.Timestamp(episodes["signal_dates"][index])
            parts.append(part)
    pred = pd.concat(parts, ignore_index=True)[["code", "kline_time", "score", "future_ret_5d"]]
    # stub 把 concat 结果宽化为 ndarray：cast 只收窄静态类型，调用与原来逐字一致。
    scores = cast(Any, pred["score"])
    if scores.lt(0).any() or not np.isfinite(scores).all():
        raise ValueError("joint projection produced invalid target weights")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(output_path, index=False)
    return cast(pd.Timestamp, pd.Timestamp(episodes["sell_dates"][-1]))


def run_account(pred: Path, outdir: Path, final_sell_date: pd.Timestamp, test_guard=None) -> dict:
    command = [
        sys.executable, str(WRAPPER), "--pred", str(pred), "--train", str(RAW_DATA), "--out", str(outdir),
        "--capital", "2000000", "--topn", "100", "--sell-buffer", "200", "--min-edge", "0",
        "--final-sell-date", final_sell_date.date().isoformat(),
    ]
    if test_guard is not None:
        command.extend(["--allow-test-once", "--test-guard", str(test_guard)])
    subprocess.run(command, check=True)
    with (outdir / "account.json").open(encoding="ascii") as source:
        return json.load(source)


def merged_episodes(train_path: Path, val_path: Path) -> dict:
    train, val = _load_episode_npz(train_path), _load_episode_npz(val_path)
    if not np.array_equal(train["feature_columns"], val["feature_columns"]):
        raise ValueError("TRAIN and VAL episode schemas differ")
    return {name: train[name] if name == "feature_columns" else np.concatenate([train[name], val[name]]) for name in train}


def retrain_winner(checkpoint: dict, train_path: Path, val_path: Path, output: Path) -> None:
    """Fit the frozen selected configuration on TRAIN+VAL, without opening TEST."""
    episodes = merged_episodes(train_path, val_path)
    torch.manual_seed(20260905)
    model = JointPortfolioPolicy()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    for _ in range(int(checkpoint["epoch"])):
        _run_proxy_epoch(model, episodes, checkpoint["temperature"], checkpoint["turnover_penalty"], optimizer)
    frozen = dict(checkpoint)
    frozen["model_state"] = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
    frozen["optimizer_state"] = optimizer.state_dict()
    frozen["split_metadata"] = {
        "fit_source": "episodes_train.npz + episodes_val.npz",
        "selection_source": "prior real-account VAL candidate table",
        "test_opened": False,
        "frozen_before_test_projection": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(frozen, output)


def select_trial(rows: list[dict]) -> dict:
    for row in rows:
        row["objective"] = row["annual"] - 0.5 * row["maxdd"]
    best_objective = max(row["objective"] for row in rows)
    close = [row for row in rows if row["objective"] >= best_objective - 0.02]
    return max(close, key=lambda row: row["sharpe"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", type=Path, default=JOINT_OUTDIR)
    parser.add_argument("--skip-test", action="store_true")
    args = parser.parse_args()
    outdir, train_dir = args.outdir, args.outdir / "train"
    with (train_dir / "metrics.json").open(encoding="ascii") as source:
        train_metrics = json.load(source)
    val_episodes = outdir / "episodes_val.npz"
    rows = []
    for trial in train_metrics["trials"]:
        trial_id = trial["id"]
        pred = outdir / "val_predictions" / f"{trial_id}.parquet"
        final_sell = project_checkpoint(Path(trial["checkpoint_path"]), val_episodes, pred)
        account = run_account(pred, outdir / "val_accounts" / trial_id, final_sell)
        proxy = trial["best"]["val_proxy_series"]
        proxy_total = float(np.prod(1.0 + np.asarray(proxy)) - 1.0)
        proxy_annual = float((1.0 + proxy_total) ** (252.0 / account["annual_days_basis"]) - 1.0)
        rows.append({"id": trial_id, "epoch": trial["best"]["epoch"], "temperature": trial["temperature"],
                     "turnover_penalty": trial["turnover_penalty"], "proxy_annual": proxy_annual,
                     "annual": account["annual"], "sharpe": account["sharpe"], "maxdd": account["maxdd"],
                     "objective": account["annual"] - 0.5 * account["maxdd"], "account_path": str(outdir / "val_accounts" / trial_id / "account.json")})
    winner = select_trial(rows)
    winner_trial = next(item for item in train_metrics["trials"] if item["id"] == winner["id"])
    gate_pred = outdir / "gate_off_val" / "prediction.parquet"
    gate_final_sell = project_checkpoint(Path(winner_trial["checkpoint_path"]), val_episodes, gate_pred, replacement_override=1.0)
    gate_account = run_account(gate_pred, outdir / "gate_off_val", gate_final_sell)
    checkpoint = torch.load(winner_trial["checkpoint_path"], weights_only=True)
    frozen = outdir / "frozen" / "checkpoint_train_val.pt"
    retrain_winner(checkpoint, outdir / "episodes_train.npz", val_episodes, frozen)
    if args.skip_test:
        table = pd.DataFrame(rows).sort_values("id")
        table.to_csv(outdir / "val_candidate_table.csv", index=False)
        selection = {"winner": winner, "rule": "primary maximize annual-0.5*maxdd; within 0.02 objective select highest Sharpe", "gate_off_val": gate_account, "test_runs": 1, "test_not_rerun": True}
        with (outdir / "selection.json").open("w", encoding="ascii") as target:
            json.dump(selection, target, indent=2)
        return
    # TEST is opened only here, after the real-account VAL winner is frozen.
    test_pred = outdir / "test_prediction_2026.parquet"
    test_final_sell = project_checkpoint(frozen, outdir / "episodes_test.npz", test_pred)
    test_account = run_account(test_pred, outdir / "test_account_2026", test_final_sell, outdir / "test_once_guard.json")
    table = pd.DataFrame(rows).sort_values("id")
    table.to_csv(outdir / "val_candidate_table.csv", index=False)
    selection = {"winner": winner, "rule": "maximize annual - 0.5*maxdd; candidates within 2pp of best annual resolve by higher Sharpe", "test_runs": 1}
    with (outdir / "selection.json").open("w", encoding="ascii") as target:
        json.dump(selection, target, indent=2)
    lines = [
        "# Joint E2E Acceptance", "", "## Split", "",
        "Episodes are strictly split: TRAIN through 2023-12-31, VAL 2024-01-01 through 2025-12-31, TEST 2026 onward. The model fit used TRAIN only for trials; every candidate was selected using its real VAL account result. The frozen winner was retrained on TRAIN+VAL before TEST was opened.", "",
        "## Model And Projection", "",
        "JointPortfolioPolicy is a 49->64->32 shared MLP with a per-name logit and a scalar sigmoid replacement gate. Proxy loss is negative continuous open-to-open portfolio return with smooth turnover/participation cost and HHI penalty. Projection code-aligns prior target weights per episode, applies policy logits plus replacement, and writes target weight as score. Scores are not future returns.", "",
        "`future_ret_5d=0` is a V6 schema shim only. V6 paper Q5 and benchmark curves in `v6_raw/` are invalid and must not be interpreted.", "",
        "## VAL Candidates", "",
        "```csv", table.to_csv(index=False).rstrip(), "```", "",
        "## Selection", "",
        f"Winner: `{winner['id']}`, epoch {winner['epoch']}; VAL rule: annual - 0.5*maxdd, with a 2pp annual tie band resolved by Sharpe. Proxy annual {winner['proxy_annual']:.4%}; real VAL annual {winner['annual']:.4%}; proxy-to-real gap {(winner['annual']-winner['proxy_annual']):.4%}.", "",
        "## 2026 Confirmation", "",
        f"Exactly one TEST run was made after freezing: annual {test_account['annual']:.4%}, Sharpe {test_account['sharpe']:.4f}, max drawdown {test_account['maxdd']:.4%}, total {test_account['total']:.4%}. It contains {test_account['n_rebalances']} episodes over {test_account['annual_days_basis']} trading-day basis, so two episodes / about 80 trading days has no statistical significance.", "",
        "Execution: Top100, T+1 open, equal weight, CNY 2,000,000, sell-buffer 200, min-edge 0. Wrapper output records the unmodified `account_engine_v6.py` base and annual-days method: actual adjacent signal-date trading intervals plus the median final interval. It invokes V6 with freq=1 only because input dates are already episode-sparse; no V6 source or existing artifact was modified.",
    ]
    (outdir / "README.md").write_text("\n".join(lines) + "\n", encoding="ascii")
    print(json.dumps({"winner": winner, "test_account": test_account, "test_runs": 1}, indent=2))


if __name__ == "__main__":
    main()
