"""封存评估模块：实验登记 + 封存标志，防止研究期无意过拟合。

核心设计：
  - ``SealedManifest``：封存时的完整环境指纹（UUID、时间戳、config/数据/代码指纹）
  - ``guard_sealed``：封存守卫，匹配指纹时拒绝重跑
  - ``create_sealed_manifest``：训练+评估完成后创建封存清单

封存哲学（Quant Arena）：
  封存数据只评一次，限制研究期反复试探。封存清单绑定到 run_log_dir，
  一旦封存，相同路径+相同配置不可重跑。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SEALED_MANIFEST_FILENAME = "sealed_manifest.json"


class SealedEvalError(RuntimeError):
    """封存拒绝：该运行目录已被封存且指纹匹配，不可重跑。"""

    def __init__(self, manifest_path: str, experiment_id: str):
        self.manifest_path = manifest_path
        self.experiment_id = experiment_id
        super().__init__(
            f"封存拒绝: {manifest_path} (experiment_id={experiment_id}) "
            f"已被封存且指纹匹配。如需重跑请使用新目录或清除封存清单。"
        )


def _compute_file_sha1(filepath: str, chunk_size: int = 2 ** 16) -> str:
    """计算文件的 SHA1 哈希（分块读取，避免大文件内存爆炸）。

    Args:
        filepath: 文件路径
        chunk_size: 每块大小（默认 64KB）

    Returns:
        十六进制 SHA1 字符串

    Raises:
        FileNotFoundError: 文件不存在
    """
    sha1 = hashlib.sha1()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha1.update(chunk)
    return sha1.hexdigest()


def _compute_code_fingerprint(repo_root: str | None = None) -> str:
    """计算代码目录指纹：git commit hash + dirty flag。

    使用 ``git rev-parse HEAD`` 获取当前 commit，
    ``git diff --quiet`` 判断是否有未提交修改。

    Args:
        repo_root: Git 仓库根目录（默认当前工作目录）

    Returns:
        ``commit_hash[:12] + ("-dirty" if dirty else "")`` 形式的指纹

    Raises:
        RuntimeError: git 命令执行失败
    """
    cwd = repo_root or os.getcwd()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, cwd=cwd,
        ).stdout.strip()
        short = commit[:12]
        ret = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True, cwd=cwd,
        )
        dirty = ret.returncode != 0
        return f"{short}{'-dirty' if dirty else ''}"
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(f"无法获取 git 指纹: {e}") from e


def _compute_config_digest(config: dict) -> str:
    """计算完整 config dict 的 SHA1 指纹（JSON 序列化后哈希）。

    排除 `BINS`/`CENTERS` 等大型数组的逐元素差异（用 repr 替代），
    保证不同运行的同参配置产生相同指纹。

    Args:
        config: 完整训练配置 dict

    Returns:
        十六进制 SHA1 字符串（前 16 位）
    """
    # 排除 runtime-only 键（每次运行不同，不属实验定义）
    excluded_keys = {"run_log_dir", "LOG_DIR", "SCALER_PATH", "DEVICE"}
    canonical: dict[str, Any] = {}
    for k, v in config.items():
        if k in excluded_keys:
            continue
        if isinstance(v, (list, tuple)) and any(isinstance(x, float) for x in v):
            # BINS/CENTERS 等浮点数组：用 repr 确保跨运行确定性
            canonical[k] = repr(v)
        else:
            canonical[k] = v
    dumped = json.dumps(canonical, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(dumped.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SealedManifest:
    """封存清单：记录封存时的完整环境指纹。

    所有字段在创建后不可变，确保封存记录的完整性。
    """

    experiment_id: str
    """UUID 标识该次实验。"""

    sealed_at: str
    """ISO 8601 时间戳（UTC）。"""

    config_hash: str
    """完整 config dict 的 SHA1 摘要（前 16 位 hex）。"""

    data_fingerprint: str
    """数据文件 SHA1 哈希（完整文件，分块 64KB 计算）。"""

    code_fingerprint: str
    """代码目录指纹：``commit_hash[:12] + ("-dirty" if dirty else "")``。"""

    train_range: tuple[str, str]
    """训练区间 ``(start, end)``。"""

    val_range: tuple[str, str]
    """验证区间 ``(start, end)``（封存时的验证集）。"""

    sealed_range: tuple[str, str]
    """封存评估区间 ``(start, end)``，必须完全在验证集之外。"""

    metrics_snapshot: dict = field(default_factory=dict)
    """封存时的指标快照（最终损失、准确率等）。"""

    def save(self, path: str) -> None:
        """将封存清单序列化为 JSON 文件并持久化。

        Args:
            path: 目标文件路径（父目录必须已存在）
        """
        payload = asdict(self)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("封存清单已保存: %s (experiment_id=%s)", path, self.experiment_id)

    @classmethod
    def load(cls, path: str) -> SealedManifest:
        """从 JSON 文件加载封存清单。

        Args:
            path: JSON 文件路径

        Returns:
            反序列化的 SealedManifest 实例

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: 文件格式错误
            TypeError: 字段不匹配
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # 将 sealed_range / train_range / val_range 从 list 转 tuple
        for key in ("train_range", "val_range", "sealed_range"):
            if key in data and isinstance(data[key], list):
                data[key] = tuple(data[key])
        return cls(**data)

    def verify_fingerprint(self, config: dict, parquet_path: str | None = None) -> bool:
        """验证当前环境的指纹与封存清单是否匹配。

        Args:
            config: 当前运行的完整配置 dict
            parquet_path: 数据文件路径（None 时不验证数据指纹）

        Returns:
            True 指纹完全匹配, False 任一指纹不匹配
        """
        # 检查 config_hash
        current_config_hash = _compute_config_digest(config)
        if current_config_hash != self.config_hash:
            logger.warning(
                "config_hash 不匹配: manifest=%s current=%s",
                self.config_hash, current_config_hash,
            )
            return False

        # 检查数据指纹
        if parquet_path is not None and os.path.isfile(parquet_path):
            try:
                current_data_fp = _compute_file_sha1(parquet_path)
                if current_data_fp != self.data_fingerprint:
                    logger.warning(
                        "data_fingerprint 不匹配: manifest=%s current=%s",
                        self.data_fingerprint, current_data_fp,
                    )
                    return False
            except (OSError, FileNotFoundError) as e:
                logger.warning("数据指纹验证失败: %s", e)
                return False

        # 检查代码指纹
        try:
            current_code_fp = _compute_code_fingerprint()
            if current_code_fp != self.code_fingerprint:
                logger.warning(
                    "code_fingerprint 不匹配: manifest=%s current=%s",
                    self.code_fingerprint, current_code_fp,
                )
                return False
        except RuntimeError as e:
            logger.warning("代码指纹验证失败: %s", e)
            return False

        return True


def is_sealed(manifest_path: str) -> bool:
    """检查指定路径的封存清单是否存在且可解析。

    Args:
        manifest_path: 封存清单文件路径

    Returns:
        True 该路径已被有效封存, False 不存在或解析失败
    """
    if not os.path.isfile(manifest_path):
        return False
    try:
        SealedManifest.load(manifest_path)
        return True
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning("封存清单解析失败，视为未封存: %s — %s", manifest_path, e)
        return False


def guard_sealed(manifest_path: str, config: dict, parquet_path: str | None = None) -> None:
    """封存守卫：检查指定路径是否已被封存且指纹匹配。

    Args:
        manifest_path: 封存清单路径
        config: 当前运行的配置 dict（供指纹验证）
        parquet_path: 数据文件路径（None 时不验证数据指纹）

    Raises:
        SealedEvalError: 封存清单存在且指纹匹配（拒绝重跑）
    """
    if not os.path.isfile(manifest_path):
        return  # 不存在封存清单，通过

    try:
        manifest = SealedManifest.load(manifest_path)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning("封存清单损坏（%s），视为未封存: %s", manifest_path, e)
        return

    if manifest.verify_fingerprint(config, parquet_path):
        raise SealedEvalError(manifest_path, manifest.experiment_id)
    else:
        logger.warning(
            "封存清单存在但指纹不匹配，允许重跑: %s (experiment_id=%s)",
            manifest_path, manifest.experiment_id,
        )


def create_sealed_manifest(
    config: dict,
    train_range: tuple[str, str],
    val_range: tuple[str, str],
    sealed_range: tuple[str, str],
    metrics_snapshot: dict | None = None,
    parquet_path: str | None = None,
    output_dir: str | None = None,
) -> SealedManifest:
    """创建封存清单，自动计算环境指纹。

    Args:
        config: 完整训练配置 dict
        train_range: 训练区间 ``(start, end)``
        val_range: 验证区间 ``(start, end)``
        sealed_range: 封存评估区间 ``(start, end)``
        metrics_snapshot: 指标快照 dict（可选）
        parquet_path: 数据文件路径（用于计算数据指纹；None 时不计算）
        output_dir: 保存目录（None 时不自动保存）

    Returns:
        创建的 SealedManifest 实例

    Raises:
        RuntimeError: git 指纹获取失败
    """
    # 计算 config 指纹
    config_hash = _compute_config_digest(config)

    # 计算数据文件指纹
    if parquet_path and os.path.isfile(parquet_path):
        data_fingerprint = _compute_file_sha1(parquet_path)
    else:
        data_fingerprint = "no_data_file"
        logger.warning("数据文件不可用，数据指纹设为 'no_data_file'")

    # 计算代码指纹
    code_fingerprint = _compute_code_fingerprint()

    manifest = SealedManifest(
        experiment_id=str(uuid.uuid4()),
        sealed_at=datetime.now(UTC).isoformat(),
        config_hash=config_hash,
        data_fingerprint=data_fingerprint,
        code_fingerprint=code_fingerprint,
        train_range=train_range,
        val_range=val_range,
        sealed_range=sealed_range,
        metrics_snapshot=metrics_snapshot or {},
    )

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        manifest.save(os.path.join(output_dir, SEALED_MANIFEST_FILENAME))

    return manifest
