"""training 包门面：只做重导出，无逻辑（T19）。

canonical 位置：
- 编排 → training.trainer.Trainer；早停 → training.early_stopping.EarlyStopping
- 断点续训 → training.checkpoint（save/load/extract_state_dict，T14 单事实源）
- 装配 + eval 解析 → training.preprocessing（configure_preprocessing/resolve_eval_*，T08）
- 构建规则 → training.factory（build_model/build_criterion，直引，不经包根转导）
"""

from .checkpoint import extract_state_dict, load_checkpoint, load_model_state, save_checkpoint
from .early_stopping import EarlyStopping
from .preprocessing import (
    DEFAULT_ROLLING_SCOPE,
    ROLLING_SCOPES,
    EvalPreprocessing,
    configure_preprocessing,
    default_scaler_path,
    load_run_config,
    resolve_eval_featurenum,
    resolve_eval_mode_scope,
    resolve_eval_scaler_path,
)
from .trainer import Trainer

__all__ = ['DEFAULT_ROLLING_SCOPE', 'ROLLING_SCOPES', 'EarlyStopping', 'EvalPreprocessing',
           'Trainer', 'configure_preprocessing', 'default_scaler_path', 'extract_state_dict',
           'load_checkpoint', 'load_model_state', 'load_run_config', 'resolve_eval_featurenum',
           'resolve_eval_mode_scope', 'resolve_eval_scaler_path', 'save_checkpoint']
