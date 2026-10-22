"""Write a tiny whisper.cpp model with random weights, for exercising the real binding.

The model recognises nothing; it lets tests load whisper.cpp from a local path,
run a transcription, and check callbacks, cancellation, and log silencing
without the 148 MB ggml-base download. Layout follows whisper.cpp's
models/convert-pt-to-ggml.py.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

N_VOCAB = 51864  # English-only vocabulary size; whisper.cpp adds the special tokens
N_AUDIO_CTX = 1500
N_TEXT_CTX = 448
N_MELS = 80


def _linear(prefix: str, n_in: int, n_out: int, bias: bool = True) -> list[tuple[str, tuple]]:
    out = [(f"{prefix}.weight", (n_out, n_in))]
    if bias:
        out.append((f"{prefix}.bias", (n_out,)))
    return out


def _attention(prefix: str, state: int) -> list[tuple[str, tuple]]:
    return (
        _linear(f"{prefix}.query", state, state)
        + _linear(f"{prefix}.key", state, state, bias=False)
        + _linear(f"{prefix}.value", state, state)
        + _linear(f"{prefix}.out", state, state)
    )


def _norm(prefix: str, state: int) -> list[tuple[str, tuple]]:
    return [(f"{prefix}.weight", (state,)), (f"{prefix}.bias", (state,))]


def _tensors(state: int, layers: int) -> list[tuple[str, tuple]]:
    names: list[tuple[str, tuple]] = [
        ("encoder.positional_embedding", (N_AUDIO_CTX, state)),
        ("encoder.conv1.weight", (state, N_MELS, 3)),
        ("encoder.conv1.bias", (state,)),
        ("encoder.conv2.weight", (state, state, 3)),
        ("encoder.conv2.bias", (state,)),
    ]
    for i in range(layers):
        block = f"encoder.blocks.{i}"
        names += _attention(f"{block}.attn", state) + _norm(f"{block}.attn_ln", state)
        names += _linear(f"{block}.mlp.0", state, 4 * state)
        names += _linear(f"{block}.mlp.2", 4 * state, state)
        names += _norm(f"{block}.mlp_ln", state)
    names += _norm("encoder.ln_post", state)
    names += [
        ("decoder.positional_embedding", (N_TEXT_CTX, state)),
        ("decoder.token_embedding.weight", (N_VOCAB, state)),
    ]
    for i in range(layers):
        block = f"decoder.blocks.{i}"
        names += _attention(f"{block}.attn", state) + _norm(f"{block}.attn_ln", state)
        names += _attention(f"{block}.cross_attn", state)
        names += _norm(f"{block}.cross_attn_ln", state)
        names += _linear(f"{block}.mlp.0", state, 4 * state)
        names += _linear(f"{block}.mlp.2", 4 * state, state)
        names += _norm(f"{block}.mlp_ln", state)
    names += _norm("decoder.ln", state)
    return names


def write_random_model(path: Path, state: int = 64, heads: int = 1, layers: int = 1) -> Path:
    rng = np.random.default_rng(0)
    with open(path, "wb") as out:
        out.write(struct.pack("i", 0x67676D6C))
        hparams = (N_VOCAB, N_AUDIO_CTX, state, heads, layers, N_TEXT_CTX, state, heads, layers)
        out.write(struct.pack("9i", *hparams))
        out.write(struct.pack("ii", N_MELS, 1))  # n_mels, f16 weights
        filters = np.abs(rng.normal(0, 0.01, (N_MELS, 201))).astype(np.float32)
        out.write(struct.pack("ii", *filters.shape))
        filters.tofile(out)
        # Byte tokens, then filler words up to the vocabulary size.
        tokens = [bytes([b]) for b in range(256)]
        tokens += [f"w{i}".encode() for i in range(N_VOCAB - len(tokens))]
        out.write(struct.pack("i", len(tokens)))
        for token in tokens:
            out.write(struct.pack("i", len(token)))
            out.write(token)
        for name, shape in _tensors(state, layers):
            data = rng.normal(0, 0.02, shape)
            if name in ("encoder.conv1.bias", "encoder.conv2.bias"):
                data = data.reshape(shape[0], 1)
            small = data.ndim < 2 or name.endswith(
                ("positional_embedding", "conv1.bias", "conv2.bias")
            )
            data = data.astype(np.float32 if small else np.float16)
            encoded = name.encode()
            out.write(struct.pack("iii", data.ndim, len(encoded), 0 if small else 1))
            for dim in reversed(data.shape):
                out.write(struct.pack("i", dim))
            out.write(encoded)
            data.tofile(out)
    return path
