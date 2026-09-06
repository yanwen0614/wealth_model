# criterion/ — EMDLoss 唯一损失

- `emd_loss.py` 有序分类损失，`train.py:72,225` 以 `EMDLoss(num_classes=52, p=2, label_smoothing, smooth_eps=0.1)` 实例化；旧 `training/custom_loss.py` 已删。
- 改损失保持 `(logits[batch,52], labels[batch])` 签名与 `Trainer` 兼容。
