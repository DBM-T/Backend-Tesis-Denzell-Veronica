"""
rns_module/trainer.py
════════════════════════════════════════════════════════════
Entrenamiento del modelo SASNN con los pares de rns_training_pairs.
Ejecutar desde CLI:  python -m rns_module.trainer
════════════════════════════════════════════════════════════
"""
import asyncio
import json
from pathlib import Path

import asyncpg
import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import accuracy_score, f1_score
from loguru import logger

from .model import SASNN, ContrastiveLoss
from config import get_settings

_s = get_settings()


class PartsDataset(Dataset):
    def __init__(self, pairs: list[dict]):
        self.pairs = pairs

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        p = self.pairs[idx]
        return p["description_a"], p["description_b"], float(p["label"])


async def load_training_pairs() -> list[dict]:
    """Carga pares validados de la BD."""
    conn = await asyncpg.connect(dsn=_s.database_url)
    rows = await conn.fetch(
        """
        SELECT description_a, description_b, label
        FROM rns_training_pairs
        WHERE validated_at IS NOT NULL
        ORDER BY created_at
        """
    )
    await conn.close()
    return [dict(r) for r in rows]


def train(
    epochs: int = 10,
    batch_size: int = 32,
    lr: float = 1e-4,
    val_split: float = 0.2,
):
    pairs = asyncio.run(load_training_pairs())
    logger.info(f"Pares de entrenamiento: {len(pairs)}")

    # Split train / val
    split = int(len(pairs) * (1 - val_split))
    train_ds = PartsDataset(pairs[:split])
    val_ds   = PartsDataset(pairs[split:])

    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_dl   = DataLoader(val_ds,   batch_size=batch_size)

    model = SASNN(encoder_name=_s.rns_encoder_name)
    criterion = ContrastiveLoss(margin=1.0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)

    best_f1 = 0.0
    weights_path = Path(_s.rns_model_path)
    weights_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, epochs + 1):
        # ── Entrenamiento ──────────────────────────────────────
        model.train()
        total_loss = 0.0
        for desc_a, desc_b, labels in train_dl:
            emb_a, emb_b = model(list(desc_a), list(desc_b))
            loss = criterion(emb_a, emb_b, labels.float())
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        # ── Validación ─────────────────────────────────────────
        model.eval()
        y_true, y_pred = [], []
        with torch.no_grad():
            for desc_a, desc_b, labels in val_dl:
                scores = model.similarity(list(desc_a)[0], list(desc_b))
                preds  = [1 if s >= _s.rns_similarity_threshold else 0 for s in scores]
                y_true.extend(labels.int().tolist())
                y_pred.extend(preds)

        acc = accuracy_score(y_true, y_pred)
        f1  = f1_score(y_true, y_pred, zero_division=0)
        logger.info(
            f"Epoch {epoch}/{epochs} | loss={total_loss/len(train_dl):.4f} "
            f"| acc={acc:.4f} | F1={f1:.4f}"
        )

        if f1 > best_f1:
            best_f1 = f1
            torch.save(model.state_dict(), weights_path)
            logger.info(f"  ✔ Mejor modelo guardado (F1={f1:.4f})")

    logger.info(f"Entrenamiento completo. Mejor F1: {best_f1:.4f}")
    return {"best_f1": best_f1, "accuracy": acc}


if __name__ == "__main__":
    train(epochs=10, batch_size=16)
