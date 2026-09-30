//! In-place format-v3 bit updater (arms A2, A2-2p, A2b, A2b-2p, each with a
//! `+tail` variant; A2b heap reuse).
//! Design: spike/inplace_update/UPDATER_DESIGN.md. Format:
//! spike/inplace_update/FORMAT_V3.md.

pub mod apply;
pub mod batch;
pub mod freelist;
pub mod guard;
pub mod heapfree;
pub mod layout;
pub mod lists;
pub mod plsim;
pub mod readers;
pub mod search;
pub mod store;
pub mod summary;
pub mod synth;
pub mod util;
pub mod verify;
