//! E8 dv-v2 validation stress (2026-07-10): randomized + adversarial inputs
//! through the PUBLIC codec API — round-trip error bound, SIMD dot vs an f64
//! scalar reference, and the degenerate docs the unit tests don't cover
//! (single element, f16-underflow vmax, f16-overflow vmax, max-length dgaps).
//! Deterministic (LCG seeds) so a failure is reproducible.

use vectorium::core::vector::{PackedVectorView, SparseVectorView};
use vectorium::core::vector_encoder::{QueryEvaluator, SparseDataEncoder, VectorEncoder};
use vectorium::encoders::dotvbyte_fixedu8::DotVByteFixedU8Encoder;

const DIM: usize = 30522; // SPLADE vocab-sized component space

fn lcg(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    *state >> 11
}

fn rand_f32(state: &mut u64, lo: f32, hi: f32) -> f32 {
    lo + (lcg(state) % 1_000_000) as f32 / 1_000_000.0 * (hi - lo)
}

fn v2_encoder() -> DotVByteFixedU8Encoder {
    let mut e = DotVByteFixedU8Encoder::new(DIM, DIM);
    e.set_per_doc_scale(true);
    e
}

/// Encode → decode; every value must be within vmax/255 of the original
/// (u8 half-step + f16 vmax rounding), vmax taken post-f16.
fn assert_roundtrip(encoder: &DotVByteFixedU8Encoder, components: &[u16], originals: &[f32]) {
    let mut buffer: Vec<u64> = Vec::new();
    encoder.push_encoded_per_doc(components, originals, &mut buffer);
    let decoded = encoder.decode_vector(PackedVectorView::new(&buffer));
    assert_eq!(decoded.components(), components, "component drift");
    let vmax = half::f16::from_f32(originals.iter().fold(0.0f32, |a, &b| a.max(b))).to_f32();
    let step = if vmax > 0.0 { vmax / 255.0 } else { 0.0 };
    for ((&c, &orig), &dec) in components.iter().zip(originals).zip(decoded.values()) {
        assert!(
            (orig - dec).abs() <= step + 1e-9,
            "component {c}: |{orig} - {dec}| > step {step} (vmax {vmax})"
        );
    }
}

#[test]
fn stress_random_docs_roundtrip_and_dot() {
    let mut seed = 0xE8D5_1234u64;
    for trial in 0..500 {
        let len = 1 + (lcg(&mut seed) as usize % 400);
        // random strictly-increasing components across the full u16 vocab
        let mut components: Vec<u16> = (0..len)
            .map(|_| (lcg(&mut seed) % DIM as u64) as u16)
            .collect();
        components.sort_unstable();
        components.dedup();
        let scale = 10f32.powf(rand_f32(&mut seed, -3.0, 1.5)); // 1e-3 .. ~30
        let originals: Vec<f32> = components
            .iter()
            .map(|_| rand_f32(&mut seed, 0.0, 1.0) * scale)
            .collect();

        let encoder = v2_encoder();
        assert_roundtrip(&encoder, &components, &originals);

        // SIMD dot vs f64 reference over the dequantized values
        let mut buffer: Vec<u64> = Vec::new();
        encoder.push_encoded_per_doc(&components, &originals, &mut buffer);
        let decoded = encoder.decode_vector(PackedVectorView::new(&buffer));

        let qlen = 1 + (lcg(&mut seed) as usize % 64);
        let mut qcomp: Vec<u16> = (0..qlen)
            .map(|_| (lcg(&mut seed) % DIM as u64) as u16)
            .collect();
        qcomp.sort_unstable();
        qcomp.dedup();
        let qvals: Vec<f32> = qcomp.iter().map(|_| rand_f32(&mut seed, 0.0, 3.0)).collect();

        let mut dense = vec![0.0f64; DIM];
        for (&c, &v) in qcomp.iter().zip(&qvals) {
            dense[c as usize] = v as f64;
        }
        let reference: f64 = decoded
            .components()
            .iter()
            .zip(decoded.values())
            .map(|(&c, &v)| dense[c as usize] * v as f64)
            .sum();

        let evaluator = encoder.query_evaluator(SparseVectorView::new(&qcomp, &qvals));
        let got = evaluator.compute_distance(PackedVectorView::new(&buffer)).0 as f64;
        let tol = 1e-3 * reference.abs().max(1.0);
        assert!(
            (got - reference).abs() <= tol,
            "trial {trial}: SIMD dot {got} vs reference {reference} (len {len})"
        );
    }
}

#[test]
fn stress_single_element_docs() {
    for &v in &[1e-4f32, 0.03, 1.0, 3.98, 11.0, 100.0, 6000.0] {
        let encoder = v2_encoder();
        assert_roundtrip(&encoder, &[123u16], &[v]);
    }
}

/// vmax so small that f16 rounds it to 0 (or subnormal) — must not panic,
/// must decode to finite values.
#[test]
fn stress_f16_underflow_vmax_is_finite() {
    for &v in &[1e-9f32, 3e-8, 6e-8, 1e-7, 1e-5] {
        let encoder = v2_encoder();
        let mut buffer: Vec<u64> = Vec::new();
        encoder.push_encoded_per_doc(&[5u16, 900], &[v, v * 0.5], &mut buffer);
        let decoded = encoder.decode_vector(PackedVectorView::new(&buffer));
        assert!(
            decoded.values().iter().all(|x| x.is_finite()),
            "underflow vmax {v} produced non-finite decode: {:?}",
            decoded.values()
        );
        // dot must also stay finite
        let evaluator = encoder.query_evaluator(SparseVectorView::new(&[5u16], &[1.0f32]));
        let got = evaluator.compute_distance(PackedVectorView::new(&buffer)).0;
        assert!(got.is_finite(), "underflow vmax {v} produced non-finite dot {got}");
    }
}

/// vmax beyond f16::MAX (65504) — f16 saturates/overflows; must not panic,
/// must decode finite. (Unreachable via the f16-dir converter, but the
/// encode API is public.)
#[test]
fn stress_f16_overflow_vmax_is_finite() {
    for &v in &[65504.0f32, 70000.0, 1e6] {
        let encoder = v2_encoder();
        let mut buffer: Vec<u64> = Vec::new();
        encoder.push_encoded_per_doc(&[0u16, 30000], &[v, 1.0], &mut buffer);
        let decoded = encoder.decode_vector(PackedVectorView::new(&buffer));
        assert!(
            decoded.values().iter().all(|x| x.is_finite()),
            "overflow vmax {v} produced non-finite decode: {:?}",
            decoded.values()
        );
        let evaluator = encoder.query_evaluator(SparseVectorView::new(&[0u16], &[1.0f32]));
        let got = evaluator.compute_distance(PackedVectorView::new(&buffer)).0;
        assert!(got.is_finite(), "overflow vmax {v} produced non-finite dot {got}");
    }
}

/// Extreme component gaps (0 and 65535 present) exercise the widest dgap
/// codes under the v2 envelope.
#[test]
fn stress_max_component_gaps() {
    let mut e = DotVByteFixedU8Encoder::new(65536, 65536);
    e.set_per_doc_scale(true);
    let components: Vec<u16> = vec![0, 1, 32768, 65534, 65535];
    let originals: Vec<f32> = vec![2.0, 0.001, 5.5, 0.5, 9.0];
    let mut buffer: Vec<u64> = Vec::new();
    e.push_encoded_per_doc(&components, &originals, &mut buffer);
    let decoded = e.decode_vector(PackedVectorView::new(&buffer));
    assert_eq!(decoded.components(), components.as_slice());
    let vmax = half::f16::from_f32(9.0).to_f32();
    for (&orig, &dec) in originals.iter().zip(decoded.values()) {
        assert!((orig - dec).abs() <= vmax / 255.0);
    }
}
