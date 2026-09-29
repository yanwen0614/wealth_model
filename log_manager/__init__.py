import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime

# T18 轮转/入库立约：仅顶层 run_* 可轮转；KEEP 永不自动删；scaler 运行期产物不入库
KEEP_DIRNAME = "KEEP"
RUN_PREFIX = "run_"
SCALER_FILENAME = "scaler_per_code.pkl"
DEFAULT_KEEP_LAST_N = 10
DEFAULT_MAX_TOTAL_BYTES = 2 * 1024**3

# T19 facade 注记：LoggerManager/轮转函数的 canonical 位置即本文件（T05/T18 逻辑
# 已在此稳定，为零风险本任务不做拆分）；包根只经 __all__ 声明公共面，不新增逻辑。
__all__ = [
    "DEFAULT_KEEP_LAST_N",
    "DEFAULT_MAX_TOTAL_BYTES",
    "KEEP_DIRNAME",
    "LoggerManager",
    "RUN_PREFIX",
    "SCALER_FILENAME",
    "collect_rotation_plan",
    "prune_old_runs",
]


class LoggerManager:
    """
    日志管理器类
    职责：配置日志系统，支持同时输出到控制台和文件
    
    参数:
        log_dir: 日志根目录
        config: 配置管理器实例（可选）
    """
    def __init__(self, log_dir: str = "logs", config = None):
        self.log_dir = log_dir
        self.config = config
        
        # 创建带时间戳的日志文件夹（沿用本地 wall time，run 目录命名契约）
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 - run 目录时间戳刻意用本地时间
        self.run_log_dir = self._claim_run_dir(log_dir, self.timestamp)
        
        # 配置日志系统
        self._configure_logging()
        
        # 持久化配置（如果提供了配置）
        if self.config:
            self._save_config()

    def _claim_run_dir(self, log_dir: str, timestamp: str) -> str:
        """同秒 run_* 碰撞时递增后缀（run_xxx_01…），exist_ok=False 保证并发安全。"""
        base = os.path.join(log_dir, f"run_{timestamp}")
        try:
            os.makedirs(base, exist_ok=False)
            return base
        except FileExistsError:
            pass
        suffix = 1
        while True:
            candidate = f"{base}_{suffix:02d}"
            try:
                os.makedirs(candidate, exist_ok=False)
                return candidate
            except FileExistsError:
                suffix += 1
    
    def _configure_logging(self):
        """配置日志系统"""
        # 清除已有的日志处理器
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        
        # 日志格式
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        formatter = logging.Formatter(log_format)
        
        # 配置根日志记录器
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 文件处理器
        log_file = os.path.join(self.run_log_dir, "training.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # 记录日志初始化信息
        logger.info(f"日志系统初始化完成，日志目录: {self.run_log_dir}")
    
    def save_config(self, config=None) -> str:
        """单次发布 config.json（含 featurenum 回填后的最终快照），供 train 侧收敛双写。"""
        if config is not None:
            self.config = config
        self._save_config()
        return os.path.join(self.run_log_dir, "config.json")

    def _save_config(self):
        """将配置保存到日志目录（tmp + os.replace 原子发布，同盘同目录，Windows 兼容）"""
        config_file = os.path.join(self.run_log_dir, "config.json")
        self._atomic_write_json(config_file, self.config)

        logging.getLogger(__name__).info(f"配置已保存到: {config_file}")

    @staticmethod
    def _atomic_write_json(path: str, data) -> None:
        """先序列化再写同目录 tmp，fsync 后 os.replace 发布；失败清 tmp 且不动旧文件。"""
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(path) or ".", prefix=".config.json.", suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    
    def get_log_dir(self) -> str:
        """获取当前运行的日志目录"""
        return self.run_log_dir

    def get_timestamp(self) -> str:
        """获取当前运行的时间戳"""
        return self.timestamp


def _dir_size_bytes(path: str) -> int:
    """统计目录体积（失败按 0 计，不抛异常）。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def collect_rotation_plan(log_dir: str, *, keep_last_n: int = DEFAULT_KEEP_LAST_N,
                          max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
                          exclude: str | None = None) -> dict:
    """dry-run 轮转清单：只列顶层 run_*，KEEP/当次永不进待删，不删任何文件。"""
    exclude_abs = os.path.abspath(exclude) if exclude else None
    runs: list[str] = []
    for name in sorted(os.listdir(log_dir)) if os.path.isdir(log_dir) else []:
        full = os.path.join(log_dir, name)
        if not os.path.isdir(full) or not name.startswith(RUN_PREFIX):
            continue
        if KEEP_DIRNAME in os.path.abspath(full).split(os.sep):
            continue
        runs.append(full)
    runs.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)))
    keep = runs[-keep_last_n:] if keep_last_n > 0 else []
    delete = [p for p in runs[: max(0, len(runs) - len(keep))]]
    if exclude_abs and exclude_abs in delete:  # 当次挪回 keep，补删最老 keep（非当次）
        delete.remove(exclude_abs)
        keep.append(exclude_abs)
        for cand in sorted(keep, key=lambda p: (os.path.getmtime(p), os.path.basename(p))):
            if os.path.abspath(cand) != exclude_abs:
                keep.remove(cand)
                delete.append(cand)
                break
    sizes = {p: _dir_size_bytes(p) for p in keep}
    while keep and sum(sizes.values()) > max_total_bytes:  # 体积超限再从最老 keep 逐出
        victim = min(sizes, key=lambda p: (os.path.getmtime(p), os.path.basename(p)))
        if os.path.abspath(victim) == exclude_abs:
            break
        delete.append(victim)
        del sizes[victim]
        keep = [p for p in keep if p != victim]
    delete.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)))
    return {"keep": sorted(keep), "delete": sorted(delete),
            "total_bytes": sum(sizes.values()) + sum(_dir_size_bytes(p) for p in delete)}


def prune_old_runs(log_dir: str, *, keep_last_n: int = DEFAULT_KEEP_LAST_N,
                   max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
                   exclude: str | None = None, dry_run: bool = True) -> dict:
    """执行轮转：dry_run=True 只列清单；False 才删 delete 列表（仍永不删 KEEP/当次）。"""
    plan = collect_rotation_plan(log_dir, keep_last_n=keep_last_n,
                                 max_total_bytes=max_total_bytes, exclude=exclude)
    plan["dry_run"] = dry_run
    if dry_run:
        logging.getLogger(__name__).info(f"轮转 dry-run：保留 {len(plan['keep'])}，待删 {len(plan['delete'])}")
        return plan
    deleted: list[str] = []
    for path in plan["delete"]:
        if KEEP_DIRNAME in os.path.abspath(path).split(os.sep):
            continue
        if exclude and os.path.abspath(path) == os.path.abspath(exclude):
            continue
        try:
            shutil.rmtree(path)
            deleted.append(path)
        except OSError as e:
            logging.getLogger(__name__).warning(f"轮转删除失败 {path}: {e}")
    plan["deleted"] = sorted(deleted)
    return plan
