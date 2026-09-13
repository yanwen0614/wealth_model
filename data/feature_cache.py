"""跨平台 feature memmap 磁盘缓存（data 层基础模块，T01）。

职责：
- 解析缓存根目录（显式参数 > CNN_DATA_CACHE > 平台默认；Windows/Linux 均 pathlib，禁止盘符硬编码）
- 由 dataset identity/role/scope/scaler identity/seq_len/horizon/max_windows/bins/format 派生稳定短 key
- 归一化后特征与小数组原子落盘（tmp -> os.replace 新 generation，.ok 最后写，读侧只认 .ok）
- 轻量访问器 `_WindowIndex`（list-like）与 `_FeatureView`（单全局 memmap + offset，pickle 只传引用）

不变量：
- 只缓存 features（float32），标签/价格/时间保留真实小数组，不减精度
- 运行期绝不自动删除缓存；清理仅经显式 `clear_cache`
- 每个 generation 目录一旦发布不再覆盖；重复 save 递增 gen
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

CACHE_FORMAT_VERSION = "v1_memmap_cache"

_FEATURES_NAME = "features.npy"
_META_NAME = "meta.json"
_OK_NAME = ".ok"


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_cache_root(cache_dir: str | None = None) -> Path:
    """解析缓存根目录并确保存在（显式参数 > CNN_DATA_CACHE > 平台默认）。"""
    if cache_dir:
        root = Path(cache_dir).expanduser()
    elif os.environ.get("CNN_DATA_CACHE"):
        root = Path(os.environ["CNN_DATA_CACHE"]).expanduser()
    elif sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            root = Path(local).expanduser() / "cnn" / "cache"
        else:
            root = Path.home() / "AppData" / "Local" / "cnn" / "cache"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        if xdg:
            root = Path(xdg).expanduser() / "cnn"
        else:
            root = Path.home() / ".cache" / "cnn"
    root.mkdir(parents=True, exist_ok=True)
    return root


def compute_cache_key(
    base_identity: Mapping[str, Any],
    role: str,
    rolling_scope: str | None,
    scaler_identity_hash: str | None,
    seq_len: int,
    horizon: int,
    max_windows_per_code: int | None,
    bins_digest: str,
    version: str = CACHE_FORMAT_VERSION,
) -> str:
    """由影响缓存内容/索引/标签的全部字段派生稳定 16-hex 短 key。"""
    payload = {
        "cache_format_version": version,
        "base_identity": dict(base_identity),
        "role": role,
        "rolling_scope": rolling_scope,
        "scaler_identity_hash": scaler_identity_hash,
        "seq_len": int(seq_len),
        "horizon": int(horizon),
        "max_windows_per_code": None if max_windows_per_code is None else int(max_windows_per_code),
        "bins_digest": bins_digest,
    }
    return _canonical_digest(payload)[:16]


def compute_bins_digest(bins: Sequence[float]) -> str:
    """标签分箱边界的 canonical 短摘要（供 dataset 侧计算 bins_digest）。"""
    return _canonical_digest([float(b) for b in bins])[:16]


def _to_int64_ns(values: Any) -> np.ndarray:
    """datetime64 -> int64 纳秒；已是整数则原样 int64。"""
    arr = np.asarray(values)
    if np.issubdtype(arr.dtype, np.datetime64):
        arr = arr.astype("datetime64[ns]")
    return arr.astype(np.int64)


class _FeatureView:
    """单个全局 memmap + offset 的只读切片视图。

    pickle 时只写 path/offset/n/num_features，worker 侧重新 mmap，绝不复制特征矩阵。
    若底层不是 memmap（无 filename），则退化为复制数据（仅测试/内存数组场景）。
    """

    __slots__ = ("_mmap", "_path", "n", "num_features", "offset")

    def __init__(self, mmap, offset: int = 0, n: int | None = None, num_features: int | None = None):
        if n is None:
            n = int(mmap.shape[0]) - int(offset)
        raw_path = getattr(mmap, "filename", None)
        self._mmap = mmap
        self._path = os.path.abspath(str(raw_path)) if raw_path is not None else None
        self.offset = int(offset)
        self.n = int(n)
        self.num_features = int(mmap.shape[1] if num_features is None else num_features)
        if self.offset < 0 or self.n < 0:
            raise ValueError("_FeatureView 的 offset/n 不能为负")

    def subview(self, offset: int, n: int) -> _FeatureView:
        """在同一全局 memmap 上切出 per-code 视图（不复制数据）。"""
        return _FeatureView(self._mmap, offset, n, self.num_features)

    def _rows(self) -> np.ndarray:
        return self._mmap[self.offset: self.offset + self.n]

    def __array__(self, dtype=None, copy: bool | None = None):
        rows = self._rows()
        if copy:
            return np.array(rows, dtype=dtype, copy=True)
        return np.asarray(rows, dtype=dtype)

    def __getitem__(self, item):
        return self._rows()[item]

    def __len__(self) -> int:
        return self.n

    @property
    def shape(self) -> tuple[int, int]:
        return (self.n, self.num_features)

    @property
    def dtype(self) -> np.dtype:
        return self._mmap.dtype

    @property
    def T(self) -> np.ndarray:
        return self._rows().T

    def __repr__(self) -> str:
        return f"_FeatureView(shape={self.shape}, dtype={self.dtype}, path={self._path!r})"

    def __getstate__(self) -> dict:
        state: dict = {"offset": self.offset, "n": self.n, "num_features": self.num_features}
        if self._path is not None:
            state["path"] = self._path
        else:
            state["data"] = np.asarray(self._mmap)
        return state

    def __setstate__(self, state: dict) -> None:
        self.offset = int(state["offset"])
        self.n = int(state["n"])
        self.num_features = int(state["num_features"])
        if "path" in state:
            self._path = state["path"]
            self._mmap = np.load(state["path"], mmap_mode="r")
        else:
            self._path = None
            self._mmap = state["data"]


class _WindowIndex:
    """list-like 窗口索引：[N] -> (code, start)，底层紧凑 numpy 数组，pickle 体积小。"""

    __slots__ = ("_code_to_id", "code_ids", "codes", "starts")

    def __init__(self, codes: list[str], code_ids: np.ndarray, starts: np.ndarray):
        self.codes = [str(c) for c in codes]
        self.code_ids = np.asarray(code_ids, dtype=np.int32)
        self.starts = np.asarray(starts, dtype=np.int32)
        if self.code_ids.ndim != 1 or self.starts.ndim != 1:
            raise ValueError("code_ids/starts 必须是一维数组")
        if self.code_ids.shape != self.starts.shape:
            raise ValueError("code_ids 与 starts 长度不一致")
        if self.code_ids.size and int(self.code_ids.max()) >= len(self.codes):
            raise ValueError("code_ids 越界")
        self._code_to_id = {code: i for i, code in enumerate(self.codes)}

    def __len__(self) -> int:
        return int(self.starts.shape[0])

    def __getitem__(self, i: int) -> tuple[str, int]:
        n = len(self)
        if i < 0:
            i += n
        if i < 0 or i >= n:
            raise IndexError("window index out of range")
        return (self.codes[int(self.code_ids[i])], int(self.starts[i]))

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def index(self, value: tuple[str, int]) -> int:
        code, start = value
        cid = self._code_to_id.get(str(code))
        if cid is None:
            raise ValueError(f"{value!r} 不在窗口索引中")
        matches = np.flatnonzero((self.code_ids == cid) & (self.starts == int(start)))
        if matches.size == 0:
            raise ValueError(f"{value!r} 不在窗口索引中")
        return int(matches[0])

    def __getstate__(self) -> tuple:
        return (self.codes, self.code_ids, self.starts)

    def __setstate__(self, state: tuple) -> None:
        codes, code_ids, starts = state
        self.codes = [str(c) for c in codes]
        self.code_ids = np.asarray(code_ids, dtype=np.int32)
        self.starts = np.asarray(starts, dtype=np.int32)
        self._code_to_id = {code: i for i, code in enumerate(self.codes)}

    def __repr__(self) -> str:
        return f"_WindowIndex(len={len(self)}, codes={len(self.codes)})"


@dataclass
class FeatureCacheData:
    """命中缓存后返回的数据聚合；features 为全局 `_FeatureView`（共享单一 memmap）。"""

    features: _FeatureView
    future_ret: np.ndarray
    discrete: np.ndarray
    open: np.ndarray
    close: np.ndarray
    kline_time: np.ndarray
    codes: list[str]
    offsets: list[int]
    n_per_code: list[int]
    total_rows: int
    feature_cols: list[str]
    feature_cols_out: list[str]
    num_features: int
    window_code_ids: np.ndarray
    window_starts: np.ndarray
    key: str
    path: Path
    extra: dict = field(default_factory=dict)


class FeatureCache:
    """`root/<key>-g<gen>/` 磁盘缓存的原子发布与读取。

    目录内容：`features.npy`（`<f4`，[N_total, F]）、5 个小数组（[N_total]）、
    `window_code_ids.npy`/`window_starts.npy`（`<i4`）、`meta.json`、`.ok`。
    写侧永远 new generation（tmp-<pid>-<uuid> -> os.replace），读侧只认 `.ok`。
    """

    @staticmethod
    def _generations(root: Path, key: str) -> list[int]:
        prefix = f"{key}-g"
        if not root.exists():
            return []
        gens: list[int] = []
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.startswith(prefix):
                suffix = entry.name[len(prefix):]
                if suffix.isdigit():
                    gens.append(int(suffix))
        return sorted(gens)

    @staticmethod
    def _next_generation(root: Path, key: str) -> int:
        gens = FeatureCache._generations(root, key)
        return (gens[-1] + 1) if gens else 0

    @staticmethod
    def _latest_complete_dir(root: Path, key: str) -> Path | None:
        for gen in reversed(FeatureCache._generations(root, key)):
            candidate = root / f"{key}-g{gen}"
            if (candidate / _OK_NAME).exists():
                return candidate
        return None

    @classmethod
    def load(cls, root, key: str) -> FeatureCacheData | None:
        """只认 `.ok` 存在的最高 generation；未写完/异 key 一律 miss。"""
        target = cls._latest_complete_dir(Path(root), key)
        if target is None:
            return None
        return cls._load_dir(target, key)

    @classmethod
    def _load_dir(cls, target: Path, key: str) -> FeatureCacheData | None:
        try:
            meta = json.loads((target / _META_NAME).read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                print(f"[FeatureCache] 缓存回退 miss: meta 非对象 ({target})")
                return None
            if meta.get("cache_format_version") != CACHE_FORMAT_VERSION:
                print(
                    f"[FeatureCache] 缓存回退 miss: 格式版本不匹配 "
                    f"({meta.get('cache_format_version')!r} != {CACHE_FORMAT_VERSION!r})"
                )
                return None
            mmap = np.load(target / _FEATURES_NAME, mmap_mode="r")
            total = int(meta["total_rows"])
            num_features = int(meta["num_features"])
            if tuple(mmap.shape) != (total, num_features):
                print(
                    f"[FeatureCache] 缓存回退 miss: features 形状不匹配 "
                    f"({tuple(mmap.shape)} != {(total, num_features)})"
                )
                return None
            raw_extra = meta.get("extra", {})
            extra = dict(raw_extra) if isinstance(raw_extra, dict) else {}
            return FeatureCacheData(
                features=_FeatureView(mmap, 0, total, num_features),
                future_ret=np.load(target / "future_ret.npy"),
                discrete=np.load(target / "discrete.npy"),
                open=np.load(target / "open.npy"),
                close=np.load(target / "close.npy"),
                kline_time=np.load(target / "kline_time.npy"),
                codes=[str(c) for c in meta["codes"]],
                offsets=[int(v) for v in meta["offsets"]],
                n_per_code=[int(v) for v in meta["n_per_code"]],
                total_rows=total,
                feature_cols=[str(c) for c in meta["feature_cols"]],
                feature_cols_out=[str(c) for c in meta["feature_cols_out"]],
                num_features=int(meta["num_features"]),
                window_code_ids=np.load(target / "window_code_ids.npy"),
                window_starts=np.load(target / "window_starts.npy"),
                key=key,
                path=target,
                extra=extra,
            )
        except (OSError, ValueError, KeyError, EOFError) as e:
            print(f"[FeatureCache] 缓存回退 miss: {type(e).__name__}: {e}")
            return None

    @classmethod
    def save(cls, root, key: str, groups, index, *, feature_cols, feature_cols_out,
             key_components: Mapping[str, Any] | None = None,
             extra: Mapping[str, Any] | None = None) -> Path:
        """原子写入新 generation 并返回最终目录；绝不覆盖已有 key 目录。"""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        codes = [str(c) for c in groups]
        if not codes:
            raise ValueError("groups 为空，无法建立缓存")
        code_to_id = {code: i for i, code in enumerate(codes)}
        offsets: list[int] = []
        n_per_code: list[int] = []
        total = 0
        for code in codes:
            n = int(np.asarray(groups[code]["features"]).shape[0])
            offsets.append(total)
            n_per_code.append(n)
            total += n
        num_features = int(np.asarray(groups[codes[0]]["features"]).shape[1])
        window_code_ids = np.asarray([code_to_id[str(c)] for c, _ in index], dtype=np.int32)
        window_starts = np.asarray([int(s) for _, s in index], dtype=np.int32)

        for _ in range(16):
            generation = cls._next_generation(root, key)
            final = root / f"{key}-g{generation}"
            if final.exists():
                continue
            tmp = root / f"tmp-{os.getpid()}-{uuid.uuid4().hex}"
            try:
                cls._write_dir(
                    tmp, key=key, groups=groups, codes=codes, offsets=offsets,
                    n_per_code=n_per_code, total=total, num_features=num_features,
                    feature_cols=feature_cols, feature_cols_out=feature_cols_out,
                    window_code_ids=window_code_ids, window_starts=window_starts,
                    key_components=key_components, extra=extra,
                )
                try:
                    os.replace(tmp, final)
                except FileExistsError:
                    shutil.rmtree(tmp, ignore_errors=True)
                    continue
                return final
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
        raise RuntimeError(f"无法为 key={key} 分配新的缓存 generation")

    @staticmethod
    def _concat(groups, codes, field: str, dtype) -> np.ndarray:
        return np.concatenate([np.asarray(groups[c][field]).astype(dtype, copy=False) for c in codes])

    @classmethod
    def _write_dir(cls, target: Path, *, key, groups, codes, offsets, n_per_code, total,
                   num_features, feature_cols, feature_cols_out, window_code_ids,
                   window_starts, key_components, extra) -> None:
        target.mkdir(parents=True, exist_ok=False)
        features = np.lib.format.open_memmap(
            str(target / _FEATURES_NAME), mode="w+", dtype=np.float32, shape=(total, num_features)
        )
        start = 0
        for code in codes:
            chunk = np.asarray(groups[code]["features"], dtype=np.float32)
            if chunk.ndim != 2 or chunk.shape[1] != num_features:
                raise ValueError(f"{code} features 形状不匹配: {chunk.shape} != (*, {num_features})")
            features[start: start + chunk.shape[0]] = chunk
            start += chunk.shape[0]
        features.flush()
        del features
        gc.collect()

        np.save(target / "future_ret.npy", cls._concat(groups, codes, "future_ret", np.float32))
        np.save(target / "discrete.npy", cls._concat(groups, codes, "discrete", np.int64))
        np.save(target / "open.npy", cls._concat(groups, codes, "open", np.float64))
        np.save(target / "close.npy", cls._concat(groups, codes, "close", np.float64))
        kline_time = np.concatenate([_to_int64_ns(groups[c]["kline_time"]) for c in codes])
        np.save(target / "kline_time.npy", kline_time)
        np.save(target / "window_code_ids.npy", np.asarray(window_code_ids, dtype=np.int32))
        np.save(target / "window_starts.npy", np.asarray(window_starts, dtype=np.int32))

        meta = {
            "cache_format_version": CACHE_FORMAT_VERSION,
            "cache_key": key,
            "key_components": dict(key_components) if key_components else {},
            "extra": dict(extra) if extra else {},
            "feature_cols": [str(c) for c in feature_cols],
            "feature_cols_out": [str(c) for c in feature_cols_out],
            "num_features": int(num_features),
            "codes": list(codes),
            "offsets": [int(v) for v in offsets],
            "n_per_code": [int(v) for v in n_per_code],
            "total_rows": int(total),
            "n_windows": int(np.asarray(window_starts).shape[0]),
        }
        (target / _META_NAME).write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True), encoding="utf-8"
        )
        (target / _OK_NAME).write_bytes(b"")


def clear_cache(root, key: str | None = None) -> int:
    """显式删除缓存 generation 与残留 tmp 目录；运行期绝不自动调用。返回删除目录数。"""
    root = Path(root)
    if not root.exists():
        return 0
    removed = 0
    prefix = f"{key}-g" if key else None
    for entry in list(root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        is_tmp = name.startswith("tmp-")
        suffix = name.rpartition("-g")[2]
        is_generation = "-g" in name and suffix.isdigit()
        if is_tmp or (is_generation and (prefix is None or name.startswith(prefix))):
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed
