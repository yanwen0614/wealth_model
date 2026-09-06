"""逐日回测包：纯函数会计核心，numpy float64 in/out."""
from backtest.engine import BacktestResult, benchmark_nav, limit_up_mask, nav_metrics, run_backtest

__all__ = ["BacktestResult", "benchmark_nav", "limit_up_mask", "nav_metrics", "run_backtest"]
