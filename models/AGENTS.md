# models/ — 已精简为 cnn_transformer 唯一实现

- `models/__init__.py` 仅 `# package marker`，旧 `attention.py`/`cnn_lstm_attention.py` 在 `e69a47b` 删除。
- 唯一模型 `cnn_transformer/model.py:66` `CNNTransformer`（CNN 多尺度 + Transformer）。`cnn_transformer/config.py:1` 占位 `featurenum=10` 勿直接用，`train.py:58,206` 会按 `dataset.num_features`(45) 覆盖并校验。
- 改结构优先看 `inception_blocks.py:7` `LightInceptionBlock1D`（`kernels [1,3,5,7,10]` 驱动通道分配）与 `model.py:9` `PositionalEncoding`。
