"""criterion 包门面：只做重导出，无逻辑（T19）。

canonical 位置：
- 有序分类主损失 → criterion.emd_loss.EMDLoss
- 双头/纯回归变体 → criterion.dual_loss.DualLoss、criterion.pure_reg_loss.PureRegLoss
"""

from criterion.dual_loss import DualLoss as DualLoss
from criterion.emd_loss import EMDLoss as EMDLoss
from criterion.pure_reg_loss import PureRegLoss as PureRegLoss

__all__ = ["DualLoss", "EMDLoss", "PureRegLoss"]
