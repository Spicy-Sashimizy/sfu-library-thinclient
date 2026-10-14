#!/usr/bin/env python3
"""Q11-C4 ESCALATION round (the single pre-registered one, doc 11 §Q11-C4):
margin-MSE on sampled REAL doc vectors + continued training.

Loss v1 (qvec MSE) reached its floor (1.5e-4) with dev top-64 term overlap
plateaued at 0.67 — the student matches the teacher's bulk energy but not
the ordering that decides retrieval. This round adds the doc 14 §5.1
ranking-aware term: margin-MSE over doc pairs, where the docs are real
forward-index vectors from worst-case shards 1-2 (f16 mmaps, shard token ids
mapped back to vocab ids via token_to_id_map + tokenizer vocab).

For query q and docs i,j: margin error e_i - e_j with e = s_student - s_teacher
(scores = qvec . dvec). MSE over all ordered pairs of P sampled docs
== 2*Var_docs(e) per query (variance identity) — O(B*P*L) gathers, no pair loop.
Total loss = qvec_mse + lambda * margin; lambda auto-balanced once at step 1
(margin term scaled to 3x the qvec term's magnitude, then FROZEN and logged).

Init = the v1-trained checkpoint (continued training, more epochs = the
"and/or" half of the registered lever). Verdict after this round is FINAL.

Rule Zero: shards opened read-only (np.memmap mode=r); writes models/ + telemetry.
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
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402
from transformers import AutoTokenizer, BertForMaskedLM  # noqa: E402

from e6_forward_codec_proto import load_token_to_id  # noqa: E402
from stage0_candidates import open_forward  # noqa: E402
from q11_c4_train_student import (  # noqa: E402
    DATA, DEV_N, SEED, STATUS, STUDENT_DIR, TEACHER_DIR, QueryDataset,
    dev_eval, make_collate, sparse_vec)

SHARD_BASE = REPO / "data/seismic_150m/index/plan01"
DOC_SHARDS = ("global_shard1of8.mmap", "global_shard2of8.mmap")


def build_doc_pool(tokenizer, n_docs, max_nnz, rng, device):
    """Sample real doc sparse vectors from the f16 forward of shards 1-2,
    remapped shard-token-id -> vocab-id. Returns (idx, val) padded tensors."""
    vocab = tokenizer.get_vocab()
    per_shard = n_docs // len(DOC_SHARDS)
    all_idx, all_val = [], []
    for shard in DOC_SHARDS:
        d = SHARD_BASE / shard
        offs, comps, vals = open_forward(d)
        tok2id = load_token_to_id(d)
        id2vocab = np.full(max(tok2id.values()) + 1, -1, dtype=np.int64)
        for tok, sid in tok2id.items():
            vid = vocab.get(tok, -1)
            id2vocab[sid] = vid
        ndocs = len(offs) - 1
        rows = rng.sample(range(ndocs), per_shard)
        for r in rows:
            lo, hi = int(offs[r]), int(offs[r + 1])
            c = comps[lo:hi]
            v = vals[lo:hi].astype(np.float32)
            vv = id2vocab[c]
            keep = vv >= 0
            vv, v = vv[keep], v[keep]
            if len(vv) == 0:
                continue
            if len(vv) > max_nnz:
                top = np.argsort(-v)[:max_nnz]
                vv, v = vv[top], v[top]
            pad = max_nnz - len(vv)
            all_idx.append(np.pad(vv, (0, pad)))
            all_val.append(np.pad(v, (0, pad)))
    idx = torch.from_numpy(np.stack(all_idx)).to(device)
    val = torch.from_numpy(np.stack(all_val)).to(device)
    return idx, val


def doc_scores(qvecs, doc_idx, doc_val):
    """(B,V) x (P,L) -> (B,P) sparse dot products via gather."""
    g = qvecs[:, doc_idx.reshape(-1)].reshape(qvecs.shape[0], *doc_idx.shape)
    return (g * doc_val.unsqueeze(0)).sum(dim=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default=str(STUDENT_DIR / "best"))
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=192)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--warmup-steps", type=int, default=100)
    ap.add_argument("--doc-pool", type=int, default=40000)
    ap.add_argument("--docs-per-batch", type=int, default=64)
    ap.add_argument("--max-doc-nnz", type=int, default=256)
    ap.add_argument("--dev-subsample", type=int, default=512)
    args = ap.parse_args()

    t0 = time.time()
    torch.manual_seed(SEED + 1)
    torch.set_float32_matmul_precision("high")
    device = "cuda"
    rng = random.Random(SEED + 1)

    rows = [json.loads(l)["q"] for l in DATA.open()]
    train_rows, dev_rows = rows[:-DEV_N], rows[-DEV_N:]

    tokenizer = AutoTokenizer.from_pretrained(str(TEACHER_DIR))
    teacher = BertForMaskedLM.from_pretrained(str(TEACHER_DIR)).float().to(device)
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    student = BertForMaskedLM.from_pretrained(args.init).float().to(device)
    student.train()

    print(f"building doc pool ({args.doc_pool} docs from shards 1-2)...", flush=True)
    doc_idx, doc_val = build_doc_pool(tokenizer, args.doc_pool,
                                      args.max_doc_nnz, rng, device)
    print(f"doc pool: {doc_idx.shape[0]} docs, mean nnz "
          f"{(doc_val > 0).float().sum(1).mean().item():.0f}", flush=True)

    vocab = tokenizer.get_vocab()
    special_mask = torch.ones(len(vocab), device=device)
    for tok, i in vocab.items():
        if tok.startswith("["):
            special_mask[i] = 0.0
    collate = make_collate(tokenizer)
    dev_sub = rng.sample(dev_rows, min(args.dev_subsample, len(dev_rows)))
    dev_batches = [collate(dev_sub[i:i + 128]) for i in range(0, len(dev_sub), 128)]

    loader = DataLoader(QueryDataset(train_rows), batch_size=args.batch,
                        shuffle=True, num_workers=8, collate_fn=collate,
                        pin_memory=True, persistent_workers=True,
                        prefetch_factor=4, drop_last=True,
                        generator=torch.Generator().manual_seed(SEED + 1))
    total_steps = args.epochs * len(loader)
    opt = torch.optim.AdamW(student.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / max(1, args.warmup_steps)) *
        0.5 * (1 + math.cos(math.pi * min(1.0, s / total_steps))))

    history, best_overlap, ema_q, ema_m, lam = [], -1.0, None, None, None
    step = 0

    def write_status(phase, extra=None):
        elapsed = time.time() - t0
        eta = (elapsed / step * (total_steps - step)) if step else None
        st = {"phase": phase, "round": "escalation-marginmse",
              "date": time.strftime("%Y-%m-%d %H:%M:%S"),
              "step": step, "total_steps": total_steps,
              "epoch": round(step / len(loader), 2), "epochs": args.epochs,
              "loss_qvec_ema": ema_q, "loss_margin_ema": ema_m, "lambda": lam,
              "lr": sched.get_last_lr()[0],
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
            loss_q = F.mse_loss(sv, tv)

            sel = torch.randint(0, doc_idx.shape[0], (args.docs_per_batch,),
                                device=device)
            di, dv = doc_idx[sel], doc_val[sel]
            e = doc_scores(sv, di, dv) - doc_scores(tv, di, dv)  # (B,P)
            loss_m = 2.0 * e.var(dim=1, unbiased=False).mean()

            if lam is None:
                lam = (3.0 * loss_q / loss_m.clamp_min(1e-12)).item()
                print(f"lambda auto-balanced (frozen): {lam:.3e} "
                      f"(qvec {loss_q.item():.3e}, margin {loss_m.item():.3e})",
                      flush=True)
            loss = loss_q + lam * loss_m
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            ema_q = loss_q.item() if ema_q is None else 0.99 * ema_q + 0.01 * loss_q.item()
            ema_m = loss_m.item() if ema_m is None else 0.99 * ema_m + 0.01 * loss_m.item()

            if step % args.eval_every == 0 or step == total_steps:
                dev_mse, dev_ov = dev_eval(teacher, student, dev_batches,
                                           special_mask, device)
                history.append({"step": step, "loss_qvec_ema": round(ema_q, 6),
                                "loss_margin_ema": round(ema_m, 6),
                                "dev_mse": round(dev_mse, 6),
                                "dev_top64_overlap": round(dev_ov, 4),
                                "elapsed_s": round(time.time() - t0)})
                student.save_pretrained(str(STUDENT_DIR / "v2-latest"))
                tokenizer.save_pretrained(str(STUDENT_DIR / "v2-latest"))
                if dev_ov > best_overlap:
                    best_overlap = dev_ov
                    student.save_pretrained(str(STUDENT_DIR / "v2-best"))
                    tokenizer.save_pretrained(str(STUDENT_DIR / "v2-best"))
                write_status("training")
                print(f"step {step}/{total_steps} ep{epoch} q {ema_q:.6f} "
                      f"m {ema_m:.6f} dev_mse {dev_mse:.6f} "
                      f"dev_top64 {dev_ov:.4f} best {best_overlap:.4f}", flush=True)

    write_status("done", {"final_dev_top64_overlap":
                          history[-1]["dev_top64_overlap"] if history else None})
    print(f"DONE in {round((time.time() - t0) / 60)} min; best dev top-64 "
          f"{best_overlap:.4f}; checkpoints -> {STUDENT_DIR}/{{v2-latest,v2-best}}",
          flush=True)


if __name__ == "__main__":
    main()
