"""Process-wide model-load lock.

transformers' low_cpu_mem_usage init (accelerate init_empty_weights) patches
torch.nn.Module globally while a model is being constructed, so two model
loads racing in different threads can leave one on the meta device
("Cannot copy out of meta tensor; no data!" — observed 2026-07-18 when the
dense warm-cache worker and a request thread loaded models concurrently, and
as a transient ImportError in the SPLADE leg on first federated query).
Every HF/sentence-transformers model construction in this process must hold
this lock. RLock: a loader may trigger a nested load on the same thread.
"""

import threading

HF_LOAD_LOCK = threading.RLock()
