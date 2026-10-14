#!/usr/bin/env python3
"""Q11-C4 step 3: distill the 4-layer student from the reconstructed teacher
(doc 11 §Q11-C4, loss v1 — pre-registered 2026-07-28).

Student = teacher embeddings + encoder layers 1-4 + MLM head (warm start).
Loss v1 = MSE between student and teacher sparse query vectors in
`log(1+ReLU(logits))` max-pool space (the serving space; retrieval score is
linear in the qvec, so qvec error bounds every doc-score error). Teacher
frozen, fp32 + TF32 matmuls (no reduced-precision targets — the gate bar is
0.99). Padded positions are zeroed before the max-pool: serving encodes
batch-of-1 with no pads, so masking pads reproduces serving exactly.

Telemetry for the hourly reporter: `data/eval_results/_q11_c4_train_status.json`
rewritten at every eval (phase, step/total, loss EMA, dev MSE, dev top-64
term overlap vs teacher, lr, ETA, history). Checkpoints:
`models/sfu-splade-student-l4/{latest,best}` (best by dev top-64 overlap).

Rule Zero: reads only the distill jsonl + teacher dir; writes models/ + telemetry.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from transformers import AutoTokenizer, BertConfig, BertForMaskedLM  # noqa: E402

TEACHER_DIR = REPO / "models/sfu-splade-teacher-torch"
STUDENT_DIR = REPO / "models/sfu-splade-student-l4"
DATA = REPO / "data/eval_results/_q11_c4_distill_set.jsonl"
STATUS = REPO / "data/eval_results/_q11_c4_train_status.json"
DEV_N = 2000
MAX_LEN = 64
SEED = 20260728


class QueryDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]


def make_collate(tokenizer):
    def collate(batch):
        return tokenizer(batch, max_length=MAX_LEN, truncation=True,
                         padding=True, return_tensors="pt")
    return collate


def sparse_vec(logits, attention_mask):
    """log1p(relu(logits)) max-pooled over real positions (pads zeroed)."""
    act = torch.log1p(torch.relu(logits))
    act = act * attention_mask.unsqueeze(-1)
    return act.max(dim=1).values  # (B, vocab)


def build_student(teacher, n_layers):
    cfg = BertConfig.from_dict(teacher.config.to_dict())
    cfg.num_hidden_layers = n_layers
    student = BertForMaskedLM(cfg).float()
    tsd = teacher.state_dict()
    ssd = {}
    for name, ref in student.state_dict().items():
        if name in tsd and tsd[name].shape == ref.shape:
            ssd[name] = tsd[name].clone()
        else:
            ssd[name] = ref
    student.load_state_dict(ssd)
    student.tie_weights()
    return student


@torch.no_grad()
def dev_eval(teacher, student, dev_batches, special_mask, device, top_k=64):
    teacher.eval(); student.eval()
    mses, overlaps = [], []
    for enc in dev_batches:
        enc = {k: v.to(device) for k, v in enc.items()}
        tv = sparse_vec(teacher(**enc).logits, enc["attention_mask"])
        sv = sparse_vec(student(**enc).logits, enc["attention_mask"])
        mses.append(F.mse_loss(sv, tv).item())
        tvm = tv * special_mask
        svm = sv * special_mask
        tt = tvm.topk(top_k, dim=1).indices
        st = svm.topk(top_k, dim=1).indices
        for i in range(tt.shape[0]):
            a = set(tt[i].tolist()); b = set(st[i].tolist())
            overlaps.append(len(a & b) / top_k)
    student.train()
    return (sum(mses) / len(mses),
            sum(overlaps) / len(overlaps))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--dev-subsample", type=int, default=512)
    ap.add_argument("--warmup-steps", type=int, default=500)
    args = ap.parse_args()

    t0 = time.time()
    torch.manual_seed(SEED)
    torch.set_float32_matmul_precision("high")  # TF32 on Ada, fp32 accumulate
    device = "cuda"

    rows = [json.loads(l)["q"] for l in DATA.open()]
    train_rows, dev_rows = rows[:-DEV_N], rows[-DEV_N:]

    tokenizer = AutoTokenizer.from_pretrained(str(TEACHER_DIR))
    teacher = BertForMaskedLM.from_pretrained(str(TEACHER_DIR)).float().to(device)
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    student = build_student(teacher, args.layers).to(device)
    student.train()

    # dims never emitted by serving (special/[unused] tokens) — excluded from
    # the dev top-64 metric, same filter as encode_splade's '['-prefix skip
    vocab = tokenizer.get_vocab()
    special_mask = torch.ones(len(vocab), device=device)
    for tok, idx in vocab.items():
        if tok.startswith("["):
            special_mask[idx] = 0.0
    collate = make_collate(tokenizer)
    rng = random.Random(SEED)
    dev_sub = rng.sample(dev_rows, min(args.dev_subsample, len(dev_rows)))
    dev_batches = [collate(dev_sub[i:i + 128])
                   for i in range(0, len(dev_sub), 128)]

    loader = DataLoader(QueryDataset(train_rows), batch_size=args.batch,
                        shuffle=True, num_workers=8, collate_fn=collate,
                        pin_memory=True, persistent_workers=True,
                        prefetch_factor=4, drop_last=True,
                        generator=torch.Generator().manual_seed(SEED))
    total_steps = args.epochs * len(loader)
    opt = torch.optim.AdamW(student.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / max(1, args.warmup_steps)) *
        0.5 * (1 + math.cos(math.pi * min(1.0, s / total_steps))))

    STUDENT_DIR.mkdir(parents=True, exist_ok=True)
    history, best_overlap, ema = [], -1.0, None
    step = 0

    def write_status(phase, extra=None):
        elapsed = time.time() - t0
        eta = (elapsed / step * (total_steps - step)) if step else None
        st = {"phase": phase, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
              "step": step, "total_steps": total_steps,
              "epoch": round(step / len(loader), 2), "epochs": args.epochs,
              "loss_ema": ema, "lr": sched.get_last_lr()[0],
              "best_dev_top64_overlap": best_overlap,
              "elapsed_s": round(elapsed), "eta_s": round(eta) if eta else None,
              "gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
              "args": vars(args), "history": history[-50:]}
        if extra:
            st.update(extra)
        STATUS.write_text(json.dumps(st, indent=2))

    write_status("starting")
    for epoch in range(args.epochs):
        for enc in loader:
            enc = {k: v.to(device, non_blocking=True) for k, v in enc.items()}
            with torch.no_grad():
                tv = sparse_vec(teacher(**enc).logits, enc["attention_mask"])
            sv = sparse_vec(student(**enc).logits, enc["attention_mask"])
            loss = F.mse_loss(sv, tv)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            ema = loss.item() if ema is None else 0.99 * ema + 0.01 * loss.item()

            if step % args.eval_every == 0 or step == total_steps:
                dev_mse, dev_ov = dev_eval(teacher, student, dev_batches,
                                           special_mask, device)
                history.append({"step": step, "loss_ema": round(ema, 6),
                                "dev_mse": round(dev_mse, 6),
                                "dev_top64_overlap": round(dev_ov, 4),
                                "elapsed_s": round(time.time() - t0)})
                student.save_pretrained(str(STUDENT_DIR / "latest"))
                tokenizer.save_pretrained(str(STUDENT_DIR / "latest"))
                if dev_ov > best_overlap:
                    best_overlap = dev_ov
                    student.save_pretrained(str(STUDENT_DIR / "best"))
                    tokenizer.save_pretrained(str(STUDENT_DIR / "best"))
                write_status("training")
                print(f"step {step}/{total_steps} ep{epoch} loss_ema {ema:.5f} "
                      f"dev_mse {dev_mse:.5f} dev_top64 {dev_ov:.4f} "
                      f"best {best_overlap:.4f}", flush=True)

    write_status("done", {"final_dev_top64_overlap": history[-1]["dev_top64_overlap"]
                          if history else None})
    print(f"DONE in {round((time.time() - t0) / 60)} min; "
          f"best dev top-64 overlap {best_overlap:.4f}; "
          f"checkpoints -> {STUDENT_DIR}/{{latest,best}}", flush=True)


if __name__ == "__main__":
    main()
