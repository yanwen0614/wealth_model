"""训练批次与模型输出的兼容解包及损失调用。"""


def _unpack_batch(batch):
    """支持 2 元 (data, y_cls) / 3 元 (data, y_cls, y_ret)。"""
    if len(batch) == 2:
        data, y_cls = batch
        return data, y_cls, None
    data, y_cls, y_ret = batch
    return data, y_cls, y_ret


def _unpack_outputs(out):
    """单头 Tensor -> (logits, None)；双头 tuple -> (logits, ret_pred)。"""
    if isinstance(out, tuple):
        logits, ret_pred = out
        return logits, ret_pred
    return out, None


def _compute_loss(criterion, logits, ret_pred, y_cls, y_ret):
    """双头 criterion 走 4 参，否则走旧 2 参。"""
    if getattr(criterion, "is_dual_head", False):
        result = criterion(logits, ret_pred, y_cls, y_ret)
        return result[0] if isinstance(result, tuple) else result
    return criterion(logits, y_cls)
