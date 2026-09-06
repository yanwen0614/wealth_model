# models/cnn_transformer — CNNTransformer

- 入口 `model.py:66` `CNNTransformer`：`MultiWindowInceptionCNN(inception_blocks.py:193)` → `proj Linear → PositionalEncoding → TransformerEncoder → LayerNorm+Linear` 输出 `[batch,52]`。
- `config.py:1` 仅定义默认值，真实 `featurenum/seq_len/num_classes` 由 `train.py:206` 按数据集校正；改 `d_model/nhead/layers/kernels` 同步改此处与 `train CNNTransformerConfig`。
- `model.py:116` `__main__` 自检 `ModelConfig()→CNNTransformer→randn[8,featurenum,seq_len]` 可做单模型冒烟，不依赖数据。
