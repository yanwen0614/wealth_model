"""Per-name continuous policy for the daily portfolio loop."""
from __future__ import annotations

import torch
from torch import nn


class DailyContinuousPolicy(nn.Module):
    """Map 49 signal features plus current weight to per-name actions."""

    def __init__(self, hidden_dim: int = 128) -> None:
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(50, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.alpha_head = nn.Linear(hidden_dim, 1)
        self.gate_head = nn.Linear(hidden_dim, 1)

    def forward(
        self, inputs: torch.Tensor, valid_mask: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if inputs.ndim not in (2, 3) or inputs.shape[-1] != 50 or inputs.shape[-2] != 1000:
            raise ValueError("inputs must have shape (batch, 1000, 50) or (1000, 50)")
        if valid_mask is not None:
            expected_shape = inputs.shape[:-1]
            if valid_mask.shape != expected_shape:
                raise ValueError(f"valid_mask must have shape {tuple(expected_shape)}")
            valid_mask = valid_mask.to(dtype=torch.bool, device=inputs.device)

        hidden = self.shared(inputs)
        alpha_logits = self.alpha_head(hidden).squeeze(-1)
        trade_gate = torch.sigmoid(self.gate_head(hidden).squeeze(-1))
        if valid_mask is not None:
            trade_gate = trade_gate * valid_mask.to(dtype=trade_gate.dtype)
        return alpha_logits, trade_gate


def target_weights(
    alpha_logits: torch.Tensor,
    trade_gate: torch.Tensor,
    current_weights: torch.Tensor,
    valid_mask: torch.Tensor | None = None,
) -> torch.Tensor:
    """Project per-name actions to a differentiable long-only portfolio."""
    if alpha_logits.shape != trade_gate.shape or alpha_logits.shape != current_weights.shape:
        raise ValueError("alpha_logits, trade_gate, and current_weights must have equal shapes")
    if alpha_logits.ndim < 1:
        raise ValueError("portfolio vectors must have at least one dimension")
    if valid_mask is None:
        valid_mask = torch.ones_like(alpha_logits, dtype=torch.bool)
    else:
        if valid_mask.shape != alpha_logits.shape:
            raise ValueError("valid_mask must match portfolio vector shape")
        valid_mask = valid_mask.to(dtype=torch.bool, device=alpha_logits.device)

    valid = valid_mask.to(dtype=alpha_logits.dtype)
    masked_logits = alpha_logits.masked_fill(~valid_mask, -torch.inf)
    has_valid = valid_mask.any(dim=-1, keepdim=True)
    safe_logits = torch.where(has_valid, masked_logits, torch.zeros_like(masked_logits))
    alpha_weights = torch.softmax(safe_logits, dim=-1) * valid

    current = torch.clamp(current_weights, min=0) * valid
    current_total = current.sum(dim=-1, keepdim=True)
    current = current / current_total.clamp_min(torch.finfo(current.dtype).tiny)

    projected = current + trade_gate * (alpha_weights - current)
    projected = torch.clamp(projected, min=0) * valid
    return projected / projected.sum(dim=-1, keepdim=True).clamp_min(torch.finfo(projected.dtype).tiny)
