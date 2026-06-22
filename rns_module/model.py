"""
rns_module/model.py
════════════════════════════════════════════════════════════
SASNN — Self-Attention Siamese Neural Network
Arquitectura basada en Cheng & Yan (2023)
Entrada: descripción textual de repuestos (str)
Salida:  score de similitud ∈ [0, 1]
Umbral:  score ≥ 0.85 → equivalentes
════════════════════════════════════════════════════════════
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from sentence_transformers import SentenceTransformer


class ContrastiveLoss(nn.Module):
    """
    Función de pérdida contrastiva.
    label=1 → par equivalente (mismo repuesto)
    label=0 → par distinto
    """
    def __init__(self, margin: float = 1.0):
        super().__init__()
        self.margin = margin

    def forward(
        self,
        emb1: torch.Tensor,
        emb2: torch.Tensor,
        label: torch.Tensor,
    ) -> torch.Tensor:
        dist = F.pairwise_distance(emb1, emb2, p=2)
        loss = (
            label * dist.pow(2)
            + (1 - label) * F.relu(self.margin - dist).pow(2)
        )
        return loss.mean()


class SASNN(nn.Module):
    """
    Self-Attention Siamese Neural Network.

    Flujo por rama:
      texto → SentenceTransformer (embedding 384-dim) →
      MultiheadAttention → Linear proyección (256-dim) → L2-norm
    """
    ENCODER_DIM = 384   # MiniLM-L12 → 384
    HIDDEN_DIM  = 256

    def __init__(self, encoder_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        super().__init__()

        # Encoder compartido (siamés — mismos pesos para ambas ramas)
        self.encoder = SentenceTransformer(encoder_name)

        # Capa de auto-atención sobre el embedding
        self.attention = nn.MultiheadAttention(
            embed_dim=self.ENCODER_DIM,
            num_heads=4,
            dropout=0.1,
            batch_first=True,
        )

        # Proyección al espacio de similitud
        self.projection = nn.Sequential(
            nn.Linear(self.ENCODER_DIM, self.HIDDEN_DIM),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(self.HIDDEN_DIM, self.HIDDEN_DIM),
        )

    # ── Rama siamesa ──────────────────────────────────────────
    def _encode(self, texts: list[str]) -> torch.Tensor:
        """Codifica una lista de textos → tensor (batch, HIDDEN_DIM) normalizado."""
        # SentenceTransformer → (batch, 384)
        raw = self.encoder.encode(
            texts,
            convert_to_tensor=True,
            show_progress_bar=False,
        )
        # Agregar dimensión de secuencia para MultiheadAttention
        x = raw.unsqueeze(1)                        # (batch, 1, 384)
        attn_out, _ = self.attention(x, x, x)       # (batch, 1, 384)
        x = attn_out.squeeze(1)                     # (batch, 384)
        x = self.projection(x)                      # (batch, 256)
        return F.normalize(x, p=2, dim=1)           # L2-norm

    # ── Forward ───────────────────────────────────────────────
    def forward(
        self,
        texts_a: list[str],
        texts_b: list[str],
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Retorna (emb_a, emb_b) — mismos pesos, entrada diferente."""
        return self._encode(texts_a), self._encode(texts_b)

    # ── Inferencia ────────────────────────────────────────────
    @torch.no_grad()
    def similarity(self, text_a: str, texts_b: list[str]) -> list[float]:
        """
        Calcula la similitud coseno entre text_a y cada elemento de texts_b.
        Como los embeddings están L2-normalizados, dot product = coseno.
        Retorna lista de scores ∈ [0, 1].
        """
        emb_a = self._encode([text_a])              # (1, 256)
        emb_b = self._encode(texts_b)               # (n, 256)
        scores = (emb_a @ emb_b.T).squeeze(0)       # (n,)
        # Convertir de [-1,1] a [0,1]
        return ((scores + 1) / 2).cpu().tolist()
