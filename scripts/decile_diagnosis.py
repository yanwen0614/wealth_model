"""十分位收益诊断 + 驼峰检测工具。

接收预测缓存 npz（exp_ret/true_ret/dates/codes），产出：
1. decile_returns.html — Plotly 十分位累计收益折线图
2. hump_report.json — 驼峰检测报告

用法：
    uv run python scripts/decile_diagnosis.py <pred_cache.npz> [--output_dir ./decile_report]
"""
from __future__ import annotations

import argparse
import json
import logging
import os

import numpy as np

from backtest.cnn_adapter.cache import load_prediction_cache

logger = logging.getLogger(__name__)

# ── 核心逻辑 ──────────────────────────────────────────────────────────────


def _decile_assign(exp_ret: np.ndarray) -> np.ndarray:
    """按 exp_ret 排序分为 10 组，返回组标号 0..9（0=最低, 9=最高）。

    使用 argsort 分位划分，每组 ≈ n/10 个元素，平局分配到更低位组。
    """
    n = len(exp_ret)
    if n < 10:
        raise ValueError(f"样本数不足（{n} < 10），无法分十分位")
    order = np.argsort(exp_ret, kind="stable")
    groups = np.empty(n, dtype=np.intp)
    bin_size = n / 10.0
    for i, idx in enumerate(order):
        groups[idx] = int(min(i / bin_size, 9))
    return groups


def daily_decile_means(
    exp_ret: np.ndarray,
    true_ret: np.ndarray,
    dates: np.ndarray,
    min_stocks: int = 20,
) -> dict[np.datetime64, np.ndarray]:
    """逐日计算十分位真实收益均值。

    Returns:
        {date: ndarray shape (10,)} — 第 d 组（0=低, 9=高）当日的 true_ret 均值。
        样本不足 min_stocks 的日期跳过。
    """
    daily: dict[np.datetime64, np.ndarray] = {}
    for d in np.unique(dates):
        mask = dates == d
        cnt = int(mask.sum())
        if cnt < min_stocks:
            logger.debug("跳过日期 %s（样本 %d < min_stocks %d）", d, cnt, min_stocks)
            continue
        e = np.asarray(exp_ret[mask], dtype=np.float64)
        r = np.asarray(true_ret[mask], dtype=np.float64)
        groups = _decile_assign(e)
        means = np.array([r[groups == g].mean() for g in range(10)])
        daily[d] = means
    if not daily:
        raise RuntimeError(
            f"无有效日期（均低于 min_stocks={min_stocks} 只股票）"
        )
    return daily


def compute_cumulative_returns(
    daily_means: dict[np.datetime64, np.ndarray],
) -> np.ndarray:
    """累计十分位收益（几何累乘）。

    Returns:
        ndarray shape (10,): 各组累计收益 = ∏(1 + r_daily) - 1。
    """
    all_days = np.array([daily_means[d] for d in sorted(daily_means)])
    cum = np.cumprod(1.0 + all_days, axis=0)[-1] - 1.0
    return cum  # shape (10,)


def detect_hump(
    cum_returns: np.ndarray,
    daily_means: dict[np.datetime64, np.ndarray],
    std_multiplier: float = 1.0,
) -> dict:
    """检测驼峰：D10 累计收益是否弱于 D8（+ 动态阈值）。

    Args:
        cum_returns: shape (10,) 各组累计收益。
        daily_means: 逐日十分位均值 {date: ndarray (10,)}。
        std_multiplier: 阈值系数（默认 1.0 倍标准差）。

    Returns:
        dict:
          - hump_detected: bool
          - max_decile: int (1-indexed, 1..10)
          - decile_cumrets: [float] 10 元素
          - d8_cumret: float
          - d10_cumret: float
          - spread_threshold: float
          - daily_spread_std: float
          - warning: str | None
    """
    d8 = cum_returns[7]  # 0-indexed → 第 8 组
    d10 = cum_returns[9]

    # 每日 spread（D10 - D8）标准差作为动态阈值
    sorted_dates = sorted(daily_means)
    spreads = np.array([daily_means[d][9] - daily_means[d][7] for d in sorted_dates])
    spread_std = float(np.std(spreads, ddof=1)) if len(spreads) > 1 else 0.0
    threshold = spread_std * std_multiplier

    max_decile = int(np.argmax(cum_returns) + 1)  # 1-indexed
    hump = bool(d10 < d8 + threshold)

    warning: str | None = None
    if hump:
        warning = (
            f"D10({d10:+.6f}) < D8({d8:+.6f}) + threshold({threshold:.6f}) "
            f"→ 驼峰模式；最高分组为 D{max_decile}"
        )
        logger.warning("⚠ 驼峰检测: %s", warning)

    return {
        "hump_detected": hump,
        "max_decile": max_decile,
        "decile_cumrets": [float(v) for v in cum_returns.tolist()],
        "d8_cumret": float(d8),
        "d10_cumret": float(d10),
        "spread_threshold": round(threshold, 8),
        "daily_spread_std": round(spread_std, 8),
        "warning": warning,
    }


# ── Plotly 可视化 ─────────────────────────────────────────────────────────


def build_decile_plot(cum_returns: np.ndarray, hump: dict) -> str:
    """生成 Plotly 十分位累计收益折线图 HTML。

    Returns:
        str: 独立 HTML 字符串（无服务器依赖）。
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.error("需要 plotly（pip install plotly）")
        raise

    groups = list(range(1, 11))
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=groups,
        y=hump["decile_cumrets"],
        mode="lines+markers",
        name="Decile",
        line={"color": "#2E86AB", "width": 2},
        marker={"size": 8, "color": "#2E86AB"},
    ))

    # 标记最高分组
    max_d = hump["max_decile"]
    fig.add_trace(go.Scatter(
        x=[max_d],
        y=[hump["decile_cumrets"][max_d - 1]],
        mode="markers",
        name=f"Max(D{max_d})",
        marker={"size": 14, "color": "#E63946", "symbol": "star"},
    ))

    # 驼峰标记
    if hump["hump_detected"]:
        fig.add_vline(
            x=8.5,
            line_dash="dash",
            line_color="#E63946",
            opacity=0.5,
            annotation_text=f"Hump (D10<D8+{hump['spread_threshold']:.4f})",
            annotation_position="top right",
        )

    title_suffix = " ⚠ 驼峰" if hump["hump_detected"] else " ✓ 单调"
    fig.update_layout(
        title=f"十分位累计收益折线图{title_suffix}",
        xaxis_title="十分位分组",
        yaxis_title="累计收益",
        xaxis={"tickmode": "array", "tickvals": groups, "ticktext": [f"D{g}" for g in groups]},
        yaxis={"tickformat": ".2%"},
        template="plotly_white",
        hovermode="x unified",
        legend={"yanchor": "top", "y": 0.99, "xanchor": "left", "x": 0.01},
        margin={"l": 60, "r": 40, "t": 60, "b": 60},
    )

    return fig.to_html(include_plotlyjs="cdn", full_html=True)


# ── CLI ────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="十分位收益诊断 + 驼峰检测（基于预测缓存 npz）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  uv run python scripts/decile_diagnosis.py logs/pred_cache.npz\n"
            "  uv run python scripts/decile_diagnosis.py logs/pred_cache.npz --output_dir ./my_report\n"
        ),
    )
    p.add_argument("pred_cache", type=str, help="预测缓存 npz 路径（exp_ret/true_ret/dates/codes）")
    p.add_argument(
        "--output_dir", type=str, default="./decile_report",
        help="输出目录（默认 ./decile_report）",
    )
    p.add_argument(
        "--min_stocks", type=int, default=20,
        help="每日最少股票数，低于此值的日期跳过（默认 20）",
    )
    p.add_argument(
        "--std_multiplier", type=float, default=1.0,
        help="驼峰检测阈值倍数（默认 1.0 倍标准差）",
    )
    p.add_argument(
        "--log_level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认 INFO）",
    )
    return p.parse_args(argv)


def run_diagnosis(
    pred_cache: str,
    output_dir: str = "./decile_report",
    min_stocks: int = 20,
    std_multiplier: float = 1.0,
) -> dict:
    """完整诊断流程：加载 → 分位 → 检测 → 输出。

    Returns:
        hump 检测报告 dict（与 detect_hump 格式一致）。
    """
    os.makedirs(output_dir, exist_ok=True)

    logger.info("加载预测缓存: %s", pred_cache)
    data = load_prediction_cache(pred_cache)
    exp_ret = np.asarray(data["exp_ret"], dtype=np.float64)
    true_ret = np.asarray(data["true_ret"], dtype=np.float64)
    dates = np.asarray(data["dates"])
    codes = np.asarray(data["codes"])

    if true_ret is None:
        raise ValueError(f"{pred_cache} 缺少 true_ret，无法计算十分位收益")

    logger.info(
        "样本数: %d, 日期: %s~%s, 股票数: %d",
        len(exp_ret), dates.min(), dates.max(), len(np.unique(codes)),
    )

    # 逐日十分位均值
    daily = daily_decile_means(exp_ret, true_ret, dates, min_stocks=min_stocks)
    logger.info("有效交易日数: %d", len(daily))

    # 累计收益
    cum = compute_cumulative_returns(daily)

    # 驼峰检测
    hump = detect_hump(cum, daily, std_multiplier=std_multiplier)

    # 输出 JSON
    report_path = os.path.join(output_dir, "hump_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(hump, f, indent=2, ensure_ascii=False)
    logger.info("驼峰报告已保存: %s", report_path)

    # 输出控制台摘要
    _print_console_summary(hump)

    # 生成 HTML
    html = build_decile_plot(cum, hump)
    html_path = os.path.join(output_dir, "decile_returns.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("十分位折线图已保存: %s", html_path)

    return hump


def _print_console_summary(hump: dict) -> None:
    """控制台打印驼峰检测摘要。"""
    print("\n" + "=" * 56)
    print("  十分位收益诊断报告")
    print("=" * 56)
    print(f"  驼峰检测: {'⚠ 是' if hump['hump_detected'] else '✓ 否'}")
    print(f"  最高分组: D{hump['max_decile']}")
    print(f"  D8 累计收益: {hump['d8_cumret']:+.4%}")
    print(f"  D10 累计收益: {hump['d10_cumret']:+.4%}")
    print(f"  每日 D10-D8 spread 标准差: {hump['daily_spread_std']:.6f}")
    print(f"  检测阈值 (1σ): {hump['spread_threshold']:.6f}")
    print("  各组累计收益:")
    for i, cr in enumerate(hump["decile_cumrets"], 1):
        marker = " ← MAX" if i == hump["max_decile"] else ""
        print(f"    D{i:2d}: {cr:+.4%}{marker}")
    if hump["warning"]:
        print(f"  ⚠ {hump['warning']}")
    print("=" * 56)


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    run_diagnosis(
        pred_cache=args.pred_cache,
        output_dir=args.output_dir,
        min_stocks=args.min_stocks,
        std_multiplier=args.std_multiplier,
    )


if __name__ == "__main__":
    main()
