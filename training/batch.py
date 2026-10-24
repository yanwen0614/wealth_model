"""训练批次与模型输出的兼容解包及损失调用。"""


def _unpack_batch(batch):
    """支持 2 元 (data, y_cls) / 3 元 (data, y_cls, y_ret) /
    4 元 (data, y_cls, y_ret, sample_weight_or_gate) / 5 元 (data, y_cls, y_ret, sample_weight, gate_label)。"""
    n = len(batch)
    if n == 2:
        data, y_cls = batch
        return data, y_cls, None, None, None
    if n == 3:
        data, y_cls, y_ret = batch
        return data, y_cls, y_ret, None, None
    if n == 4:
        data, y_cls, y_ret, extra = batch
        return data, y_cls, y_ret, extra, None
    data, y_cls, y_ret, sample_weight, gate_label = batch
    return data, y_cls, y_ret, sample_weight, gate_label


def _unpack_outputs(out):
    """单头 Tensor -> (logits, None, None)；双头 tuple -> (logits, ret_pred, None)；
    三头 tuple -> (logits, ret_pred, gate)。"""
    if isinstance(out, tuple):
        if len(out) == 3:
            logits, ret_pred, gate = out
            return logits, ret_pred, gate
        logits, ret_pred = out
        return logits, ret_pred, None
    return out, None, None


def _compute_loss(criterion, logits, ret_pred, y_cls, y_ret, sample_weight=None):
    """双头 criterion 走 4 参，否则走旧 2 参；sample_weight 可选传入。"""
    if getattr(criterion, "is_dual_head", False):
        result = criterion(logits, ret_pred, y_cls, y_ret)
        return result[0] if isinstance(result, tuple) else result
    return criterion(logits, y_cls, sample_weight=sample_weight)
