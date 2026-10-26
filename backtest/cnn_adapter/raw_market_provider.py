"""将已校验 raw 记录接入 core；来源缺少执行状态时显式拒单。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from backtest_core.contracts.market import MarketBar

from backtest.cnn_adapter.raw_market_inputs import RawMarketRecord, read_raw_market_inputs


class CnnRawMarketDataProvider:
    """按代码惰性读取 raw parquet；只有显式传入已核验状态才允许执行。"""

    def __init__(
        self,
        path: str | Path,
        *,
        signal_start: date,
        signal_end: date,
        execution_end: date,
        corporate_action_dates: frozenset[tuple[str, date]] = frozenset(),
        verified_states: Mapping[tuple[str, date], Mapping[str, object]] | None = None,
    ) -> None:
        if signal_end < signal_start or execution_end < signal_end:
            raise ValueError("date window must satisfy signal_start <= signal_end <= execution_end")
        self.path = Path(path)
        self.signal_start = signal_start
        self.signal_end = signal_end
        self.execution_end = execution_end
        self.corporate_action_dates = corporate_action_dates
        self.verified_states = verified_states or {}
        self._records: dict[str, dict[date, RawMarketRecord]] = {}
        self._bars: dict[tuple[str, date], MarketBar] = {}

    def _load(self, instrument_id: str) -> None:
        if instrument_id in self._records:
            return
        source = self.path
        if self.path.is_dir():
            source = self.path / f"{instrument_id}.parquet"
            if not source.is_file():
                raise FileNotFoundError(f"raw parquet for {instrument_id!r} not found: {source}")
        window = read_raw_market_inputs(
            source, instrument_id=instrument_id, signal_start=self.signal_start,
            signal_end=self.signal_end, execution_end=self.execution_end,
        )
        self._records[instrument_id] = {row.trading_date: row for row in window.records}

    def get_bar(self, instrument_id: str, trading_date: date) -> MarketBar | None:
        key = (instrument_id, trading_date)
        if key in self._bars:
            return self._bars[key]
        self._load(instrument_id)
        row = self._records[instrument_id].get(trading_date)
        if row is None:
            return None
        state = self.verified_states.get(key, {})
        market_state = state.get("market_state")
        st_known = state.get("st_known") is True
        reference_known = state.get("reference_known") is True
        limit_known = state.get("limit_known") is True
        market_known = market_state in ("trading", "suspended")
        bar = MarketBar(
            instrument_id=instrument_id, trading_date=trading_date,
            open=row.open, high=row.high, low=row.low, close=row.close,
            volume=row.volume_shares, amount=row.amount_yuan,
            is_trading=market_state == "trading",
            limit_up=state.get("limit_up") is True,
            limit_down=state.get("limit_down") is True,
            market_state_known=market_known, st_state_known=st_known,
            reference_known=reference_known, limit_state_known=limit_known,
            corporate_action_reference_required=key in self.corporate_action_dates,
        )
        self._bars[key] = bar
        return bar

    def get_history(self, instrument_id: str, end_date: date, lookback_days: int) -> Sequence[MarketBar]:
        if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or lookback_days < 1:
            raise ValueError(f"lookback_days must be a positive int, got {lookback_days!r}")
        self._load(instrument_id)
        dates = sorted(day for day in self._records[instrument_id] if day <= end_date)[-lookback_days:]
        return tuple(bar for day in dates if (bar := self.get_bar(instrument_id, day)) is not None)
