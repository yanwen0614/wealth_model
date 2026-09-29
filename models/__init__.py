"""models 包门面：只做重导出，无逻辑（T19）。

canonical 位置：
- 主模型 → models.cnn_transformer.model.CNNTransformer（配置见 models.cnn_transformer.config.ModelConfig）
- 散户二分类 → models.retail_friendly.model.RetailFriendlyModel（配置见 models.retail_friendly.config）
"""

from models.cnn_transformer.config import ModelConfig as ModelConfig
from models.cnn_transformer.model import CNNTransformer as CNNTransformer
from models.retail_friendly.config import RetailInferenceConfig as RetailInferenceConfig
from models.retail_friendly.config import RetailModelConfig as RetailModelConfig
from models.retail_friendly.model import RetailFriendlyModel as RetailFriendlyModel

__all__ = [
    "CNNTransformer",
    "ModelConfig",
    "RetailFriendlyModel",
    "RetailInferenceConfig",
    "RetailModelConfig",
]
