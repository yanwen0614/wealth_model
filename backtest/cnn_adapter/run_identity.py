"""为每条合成执行路径采集可复核的运行身份。"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

_MODULE_ROLES = frozenset({
    "historical_costs", "execution_audit", "run_identity", "cnn_runner",
    "core_runner", "core_cost", "core_account",
})
_ARTIFACT_ROLES = frozenset({"data", "cache", "checkpoint"})
_REPOSITORY_ROLES = frozenset({"cnn", "core"})
_DISTRIBUTIONS = frozenset({"backtest-core", "numpy", "pandas", "pydantic", "torch", "pyarrow"})


@dataclass(frozen=True)
class RunIdentity:
    """不可变身份快照；to_dict 返回可序列化的独立内容。"""

    _payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self._payload))


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True,
        text=True, check=True, encoding="utf-8",
    )
    return result.stdout


def _distribution_version(name: str) -> str:
    return metadata.version(name)


def _require_roles(value: Mapping[str, Path], required: frozenset[str], name: str) -> None:
    if not required.issubset(value) or any(not key for key in value):
        raise ValueError(f"{name}角色缺失或为空")


def _file_evidence(path: Path, role: str) -> dict[str, object]:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"{role}必须是常规文件")
        before = resolved.stat()
    except OSError as exc:
        raise ValueError(f"{role}路径或stat不可访问") from exc
    if before.st_size == 0:
        raise ValueError(f"{role}文件不能为空")
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = resolved.stat()
    except OSError as exc:
        raise ValueError(f"无法读取{role}") from exc
    stable_before = (before.st_size, before.st_mtime_ns, before.st_ino)
    stable_after = (after.st_size, after.st_mtime_ns, after.st_ino)
    if stable_before != stable_after:
        raise ValueError(f"采集期间{role}发生变化")
    return {"path": str(resolved), "size": before.st_size, "sha256": digest.hexdigest()}


def _git_evidence(root: Path, role: str) -> dict[str, object]:
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{role}仓库路径不存在或不可访问") from exc
    try:
        top_level = Path(_run_git(resolved, "rev-parse", "--show-toplevel").strip()).resolve(strict=True)
        head = _run_git(resolved, "rev-parse", "HEAD").strip()
        branch = _run_git(resolved, "branch", "--show-current").strip() or None
        status = _run_git(resolved, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise ValueError(f"{role}仓库git身份采集失败") from exc
    if not head or not resolved.is_dir():
        raise ValueError(f"{role}仓库身份缺失")
    if top_level != resolved:
        raise ValueError(f"{role}路径与git仓库根目录不一致")
    dirty = [entry for entry in status.split("\0") if entry]
    return {"path": str(resolved), "head": head, "branch": branch, "dirty": dirty}


def _loaded_module_paths(role: str) -> tuple[Path, ...]:
    if role == "run_identity":
        return (Path(__file__).resolve(),)
    suffixes = {
        "historical_costs": ("backtest.cnn_adapter.historical_costs",),
        "execution_audit": ("backtest.cnn_adapter.execution_audit",),
        "cnn_runner": ("backtest.cnn_adapter.runner",),
        "core_runner": ("account_runner",),
        "core_cost": ("policies.cost",),
        "core_account": ("contracts.account",),
    }.get(role, ())
    paths = []
    for name, module in tuple(sys.modules.items()):
        if not any(name == suffix or name.endswith("." + suffix) for suffix in suffixes):
            continue
        module_path = getattr(module, "__file__", None)
        if module_path:
            paths.append(Path(module_path).resolve(strict=True))
    if not paths:
        raise ValueError(f"模块角色{role}未在本进程实际导入")
    return tuple(paths)


def capture_run_identity(
    *, branch_label: str, repositories: Mapping[str, Path],
    modules: Mapping[str, Path], artifacts: Mapping[str, Path],
    distributions: Sequence[str],
) -> RunIdentity:
    """独立采集仓库、已导入模块、输入产物与运行依赖的身份。"""
    if not isinstance(branch_label, str) or not branch_label.strip():
        raise TypeError("branch_label必须是非空字符串")
    _require_roles(repositories, _REPOSITORY_ROLES, "仓库")
    _require_roles(modules, _MODULE_ROLES, "模块")
    _require_roles(artifacts, _ARTIFACT_ROLES, "产物")
    if not distributions or not _DISTRIBUTIONS.issubset(set(distributions)):
        raise ValueError("依赖分发包清单缺少必需项")
    if len(set(distributions)) != len(distributions):
        raise ValueError("依赖分发包名称重复")
    try:
        cnn_root = repositories["cnn"].resolve(strict=True)
        core_root = repositories["core"].resolve(strict=True)
    except OSError as exc:
        raise ValueError("仓库路径不存在或不可访问") from exc
    if cnn_root == core_root or cnn_root.is_relative_to(core_root) or core_root.is_relative_to(cnn_root):
        raise ValueError("cnn与core仓库路径不能相同或相互嵌套")
    before_git = {role: _git_evidence(path, role) for role, path in repositories.items()}
    files: dict[str, dict[str, object]] = {}
    for role, path in modules.items():
        try:
            actual_paths = _loaded_module_paths(role)
            supplied_path = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"模块{role}路径不存在或不可访问") from exc
        if supplied_path not in actual_paths:
            raise ValueError(f"模块{role}路径与实际导入路径不一致")
        files[role] = _file_evidence(path, role)
    for role, path in artifacts.items():
        files[role] = _file_evidence(path, role)
    try:
        dependencies = {name: _distribution_version(name) for name in distributions}
    except metadata.PackageNotFoundError as exc:
        raise ValueError(f"依赖包版本缺失：{exc.name}") from exc
    after_git = {role: _git_evidence(path, role) for role, path in repositories.items()}
    if before_git != after_git:
        raise ValueError("身份采集期间git仓库状态发生变化")
    payload: dict[str, object] = {
        "schema_version": 1,
        "capture_id": uuid.uuid4().hex,
        "branch_label": branch_label,
        "repositories": before_git,
        "files": files,
        "dependencies": dependencies,
        "python": platform.python_version(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["identity_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return RunIdentity(payload)


def validate_branch_identities(identities: Sequence[RunIdentity]) -> None:
    """校验分支快照独立且关键证据完整。"""
    if not identities:
        raise ValueError("至少需要一条分支身份")
    labels: set[str] = set()
    capture_ids: set[str] = set()
    for identity in identities:
        if not isinstance(identity, RunIdentity):
            raise TypeError("分支身份类型无效")
        payload = identity.to_dict()
        label = payload.get("branch_label")
        digest = payload.get("identity_hash")
        capture_id = payload.get("capture_id")
        if not isinstance(label, str) or not label.strip() or label in labels:
            raise ValueError("分支标签为空或重复")
        if not isinstance(digest, str) or not digest:
            raise ValueError("身份哈希缺失")
        if not isinstance(capture_id, str) or not capture_id or capture_id in capture_ids:
            raise ValueError("capture_id缺失或身份记录被重复复用")
        labels.add(label)
        capture_ids.add(capture_id)
        repositories = payload.get("repositories")
        if not isinstance(repositories, Mapping) or not _REPOSITORY_ROLES.issubset(repositories):
            raise ValueError("分支身份缺少仓库证据")
        files = payload.get("files")
        if not isinstance(files, Mapping) or not _MODULE_ROLES.union(_ARTIFACT_ROLES).issubset(files):
            raise ValueError("分支身份缺少文件证据")
