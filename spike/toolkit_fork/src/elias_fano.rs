//! Minimal implementation of Elias-Fano encoding.
//! This implementation is inspired by [C++ implementation](https://github.com/ot/succinct/blob/master/elias_fano.hpp) by Giuseppe Ottaviano.
use mem_dbg::{MemDbg, MemSize};
use serde::{Deserialize, Serialize};

use crate::bitfield::BitFieldGrowable;
use crate::utils::msb;
use crate::{BitVector, BitField, DArray, SelectBin};
// C1a (2026-06-27): borrow-backed view. See 07_G3_RAM_FIX_PLAN.md §4.3.
use crate::bitfield::BitFieldSlice;
use crate::darray::DArrayView;

/// Compressed monotone increasing sequence through Elias-Fano encoding.
///
/// # Example
/// ```
/// use toolkit::EliasFano;
///
/// let v: Vec<usize> = vec![1,3,4,7];
/// let ef = EliasFano::from(&v);
///
/// assert_eq!(ef.len(), 4);
/// assert_eq!(ef.universe(), 8);
///
/// assert_eq!(ef.select(0), Some(1));
/// assert_eq!(ef.select(1), Some(3));
/// assert_eq!(ef.select(2), Some(4));
/// assert_eq!(ef.select(3), Some(7));
/// ```
#[derive(Default, Debug, Clone, Serialize, Deserialize, PartialEq, MemDbg, MemSize)]
pub struct EliasFano {
    high_bits: DArray<false>,
    low_bits: BitField,
    low_len: usize,
    universe: usize,
    num_vals: usize,
}

impl EliasFano {
    /// Calculates the space usage in bits for an Elias-Fano structure
    /// given the universe size and total number of values.
    pub fn estimate_space_bits(universe: usize, num_vals: usize) -> usize {
        if num_vals == 0 {
            return 0;
        }

        let low_len = msb(universe / num_vals) as usize;

        // Total space = low_bits + high_bits
        // low_bits: low_len * num_vals
        // high_bits: (num_vals + 1) + (universe >> low_len) + 1
        low_len * num_vals + (num_vals + 1) + (universe >> low_len) + 1
    }

    /// Builds a Elias-Fano sequence from a slice of values.
    ///
    /// # Panic
    /// Panics if the sequence is not monotonically increasing.
    ///
    /// # Example
    /// ```
    /// use toolkit::EliasFano;
    ///
    /// let v1: Vec<usize> = vec![1,3,4,7];
    /// let ef1 = EliasFano::from(&v1);
    /// assert_eq!(ef1.len(), 4);
    /// ```
    pub fn from(data: &[usize]) -> EliasFano {
        if data.is_empty() {
            return EliasFano::default();
        }

        assert!(
            data.windows(2).all(|w| w[0] < w[1]),
            "The sequence must be monotonically strictly increasing."
        );

        let mut efb = EliasFanoBuilder::new(1 + data.last().unwrap(), data.len());

        efb.extend(data.iter().copied());

        efb.build()
    }

    /// Returns the position of the `k`-th smallest integer, or
    /// [`None`] if `k > self.num_vals`.
    ///
    /// # Example
    /// ```
    /// use toolkit::EliasFano;
    ///
    /// let v: Vec<usize> = vec![1,3,4,7];
    /// let ef = EliasFano::from(&v);
    ///
    /// assert_eq!(ef.select(0), Some(1));
    /// assert_eq!(ef.select(1), Some(3));
    /// assert_eq!(ef.select(2), Some(4));
    /// assert_eq!(ef.select(3), Some(7));
    /// assert_eq!(ef.select(4), None);
    /// ```
    #[inline(always)]
    pub fn select(&self, k: usize) -> Option<usize> {
        if k >= self.num_vals {
            return None;
        }

        Some(
            ((self.high_bits.select1(k)? - k) << self.low_len)
                | unsafe { self.low_bits.get_unchecked(k) as usize },
        )
    }

    /// Checks if the sequence is empty.
    pub fn is_empty(&self) -> bool {
        self.num_vals == 0
    }

    /// Returns the length of the compressed sequence.
    ///
    /// ## Examples
    /// ```
    /// use toolkit::EliasFano;
    ///
    /// let v: Vec<usize> = vec![1,3,4,7];
    /// let ef = EliasFano::from(&v);
    ///
    /// assert_eq!(ef.len(), 4);
    /// ```
    pub fn len(&self) -> usize {
        self.num_vals
    }

    /// Returns the universe, i.e., the (exclusive) upper bound of possible integers.
    ///
    /// ## Examples
    /// ```
    /// use toolkit::EliasFano;
    ///
    /// let v: Vec<usize> = vec![1,3,4,7];
    /// let ef = EliasFano::from(&v);
    ///
    /// assert_eq!(ef.universe(), 8);
    /// ```
    pub fn universe(&self) -> usize {
        self.universe
    }

    // C1a (2026-06-27): read-only accessors so the mmap writer can serialize
    // the owned EliasFano to a flat file (and so the parity test can borrow an
    // owned one into an EliasFanoView). Read-only; no risk to the search path.
    pub const fn high_bits(&self) -> &DArray<false> {
        &self.high_bits
    }
    pub const fn low_bits(&self) -> &BitField {
        &self.low_bits
    }
    pub const fn low_len(&self) -> usize {
        self.low_len
    }
    /// `num_vals` is already exposed as `len()` above; this alias mirrors the
    /// field name the writer/test reads.
    pub const fn num_vals(&self) -> usize {
        self.num_vals
    }
}

///
/// # Examples
/// ```
/// use toolkit::{EliasFano, EliasFanoBuilder};
///
/// let v: Vec<usize> = vec![1,3,4,7];
/// let mut efb = EliasFanoBuilder::new(*v.last().unwrap()+1, v.len());
///
/// for &n in v.iter(){
///     let _ = efb.push(n);
/// }
///
/// let ef = efb.build();
/// let ef = EliasFano::from(&v);
///
/// assert_eq!(ef.len(), 4);
/// assert_eq!(ef.universe(), 8);
/// ```
pub struct EliasFanoBuilder {
    high_bits: BitVector,
    low_bits: BitFieldGrowable,
    universe: usize,
    num_vals: usize,
    pos: usize,
    last: usize,
    low_len: usize,
}

impl EliasFanoBuilder {
    /// Creates a new, empty, Elias-Fano builder to store n values up to u (u excluded).
    ///
    /// # Panics
    /// Panics if `num_vals` is zero.
    pub fn new(universe: usize, num_vals: usize) -> Self {
        assert!(
            num_vals > 0,
            "The number of values num_vals must not be zero."
        );

        let low_len = msb(universe / num_vals) as usize;

        Self {
            high_bits: BitVector::with_zeros((num_vals + 1) + (universe >> low_len) + 1),
            low_bits: BitFieldGrowable::with_capacity(num_vals, low_len as u8),
            universe,
            num_vals,
            pos: 0,
            last: 0,
            low_len,
        }
    }

    /// Pushes integer `val` at the end.
    ///
    /// # Panics
    /// Panics if
    /// - `val` is less than the last one,
    /// - `val` is no less than [`Self::universe()`], or
    /// - the number of stored integers becomes no less than [`Self::num_vals()`].
    ///
    /// ## Examples
    /// ```
    /// use toolkit::{EliasFano, EliasFanoBuilder};
    ///
    /// let mut efb = EliasFanoBuilder::new(10, 3);
    /// efb.push(1);
    /// efb.push(3);
    /// efb.push(7);
    ///
    /// let ef = efb.build();
    /// assert_eq!(ef.len(), 3);
    /// ```
    pub fn push(&mut self, val: usize) {
        assert!(
            self.last <= val,
            "val must be no less than the last inserted one {}, but got {val}.",
            self.last
        );

        assert!(
            val < self.universe,
            "val must be less than self.universe()={}, but got {val}.",
            self.universe
        );
        assert!(
            self.pos < self.num_vals,
            "The number of pushed integers must not exceed self.num_vals()={}.",
            self.num_vals
        );

        self.last = val;
        let low_mask = (1 << self.low_len) - 1;

        self.low_bits.push(val as u64 & low_mask);

        self.high_bits.set((val >> self.low_len) + self.pos, true);
        self.pos += 1;
    }

    /// Appends integers at the end.
    ///
    /// # Panics
    /// Panics if
    /// - `vals` is not monotone increasing (also compared to the current last value),
    /// - values in `vals` is no less than [`Self::universe()`], or
    /// - the number of stored integers becomes no less than [`Self::num_vals()`].
    ///
    /// ## Examples
    /// ```
    /// use toolkit::{EliasFano, EliasFanoBuilder};
    ///
    /// let mut efb = EliasFanoBuilder::new(10, 3);
    /// efb.extend(vec![1, 3, 7]);
    ///
    /// let ef = efb.build();
    /// assert_eq!(ef.len(), 3);
    /// ```
    pub fn extend<I>(&mut self, vals: I)
    where
        I: IntoIterator<Item = usize>,
    {
        for x in vals {
            self.push(x);
        }
    }

    /// Builds [`EliasFano`] from the pushed integers.
    ///
    /// ## Examples
    /// ```
    /// use toolkit::{EliasFano, EliasFanoBuilder};
    ///
    /// let mut efb = EliasFanoBuilder::new(10, 3);
    /// efb.extend(vec![1, 3, 7]);
    ///
    /// let ef = efb.build();
    /// assert_eq!(ef.len(), 3);
    /// ```
    pub fn build(self) -> EliasFano {
        EliasFano {
            high_bits: DArray::new(&self.high_bits),
            low_bits: self.low_bits.into(),
            num_vals: self.num_vals,
            low_len: self.low_len,
            universe: self.universe,
        }
    }

    /// Returns the universe, i.e., the (exclusive) upper bound of possible integers.
    ///
    /// ## Examples
    /// ```
    /// use toolkit::{EliasFanoBuilder};
    ///
    /// let efb = EliasFanoBuilder::new(10, 3);
    /// assert_eq!(efb.universe(), 10);
    /// ```
    #[inline(always)]
    pub const fn universe(&self) -> usize {
        self.universe
    }

    /// Returns the number of integers that can be stored.
    ///
    /// ## Examples
    /// ```
    /// use toolkit::{EliasFanoBuilder};
    ///
    /// let efb = EliasFanoBuilder::new(10, 3);
    /// assert_eq!(efb.num_vals(), 3);
    /// ```
    #[inline(always)]
    pub const fn num_vals(&self) -> usize {
        self.num_vals
    }
}

// C1a (2026-06-27): borrow-backed twin of [`EliasFano`].
//
// `EliasFano` (above) owns `high_bits: DArray<false>` whose `bv: BitVector` is
// the owned `Box<[u64]>` alias — that pinned ownership is what re-materializes
// the anon floor when an `EliasFano` is serde-deserialized. `EliasFanoView<'a>`
// is the same structure over *borrowed* backing: `high_bits: DArrayView<'a>`
// (bv = `BitSlice<'a>` = `BitVectorGeneric<&'a [u64]>`) and `low_bits:
// BitFieldSlice<'a>` (=`BitFieldGeneric<&'a [u64]>`). The `select` algorithm is
// copied verbatim from `EliasFano::select` so the two are arithmetic twins —
// the parity argument for C1a.
//
// This is the ONLY structurally-hard piece of the C1a fork (07 §4.3): `BitField`
// could already borrow-mmap (toolkit ships `BitFieldGeneric<&[u64]>`); `DArray`
// could not, so `DArrayView` was added alongside.
#[derive(Debug, Clone, PartialEq)]
pub struct EliasFanoView<'a> {
    high_bits: DArrayView<'a>,
    low_bits: BitFieldSlice<'a>,
    low_len: usize,
    universe: usize,
    num_vals: usize,
}

impl<'a> EliasFanoView<'a> {
    /// Build an `EliasFanoView` from raw borrowed parts (the C1a reader casts
    /// an mmap region into these). The scalar fields (`low_len`/`universe`/
    /// `num_vals`) are stored inline in the on-disk manifest; the two borrowed
    /// structs point into the mmap slab.
    #[must_use]
    pub const fn from_raw_parts(
        high_bits: DArrayView<'a>,
        low_bits: BitFieldSlice<'a>,
        low_len: usize,
        universe: usize,
        num_vals: usize,
    ) -> Self {
        Self { high_bits, low_bits, low_len, universe, num_vals }
    }

    /// Returns the position of the `k`-th smallest integer, or
    /// `None` if `k > self.num_vals`. Body copied verbatim from
    /// `EliasFano::select` (elias_fano.rs:98-108).
    #[inline(always)]
    pub fn select(&self, k: usize) -> Option<usize> {
        if k >= self.num_vals {
            return None;
        }

        Some(
            ((self.high_bits.select1(k)? - k) << self.low_len)
                | unsafe { self.low_bits.get_unchecked(k) as usize },
        )
    }

    /// Checks if the sequence is empty.
    pub const fn is_empty(&self) -> bool {
        self.num_vals == 0
    }

    /// Returns the length of the compressed sequence.
    pub const fn len(&self) -> usize {
        self.num_vals
    }

    /// Returns the universe, i.e., the (exclusive) upper bound of possible integers.
    pub const fn universe(&self) -> usize {
        self.universe
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_select() {
        let v: Vec<usize> = vec![0, 12, 33, 42, 55, 61, 62, 63, 128, 129, 254, 1023];
        let ef = EliasFano::from(&v);

        for i in 0..v.len() {
            assert_eq!(ef.select(i), Some(v[i]));
        }
        assert_eq!(ef.select(v.len()), None);
    }

    // C1a (2026-06-27): the parity twin — an EliasFanoView borrow-viewing an
    // owned EliasFano must answer every select() identically.
    #[test]
    fn test_view_matches_owned() {
        use crate::{DArrayView, EliasFanoView, InventoriesView, BitSlice};
        let v: Vec<usize> = vec![0, 12, 33, 42, 55, 61, 62, 63, 128, 129, 254, 1023];
        let ef = EliasFano::from(&v);

        // Borrow the owned high-bits DArray into a DArrayView.
        let owned_da = ef.high_bits();
        let bview: BitSlice<'_> =
            unsafe { BitSlice::from_raw_parts(owned_da.bv().words(), owned_da.bv().len()) };
        let inv = owned_da.ones_inventories();
        let inv_view = InventoriesView {
            n_sets: inv.n_sets(),
            block_inventory: inv.block_inventory(),
            subblock_inventory: inv.subblock_inventory(),
            overflow_positions: inv.overflow_positions(),
        };
        let daview = DArrayView::from_raw_parts(bview, inv_view);

        // Borrow the owned low-bits BitField into a BitFieldSlice.
        let lb = ef.low_bits();
        let lb_view = lb.as_slice_view();

        let ef_view = EliasFanoView::from_raw_parts(
            daview,
            lb_view,
            ef.low_len(),
            ef.universe(),
            ef.num_vals(),
        );

        for i in 0..v.len() {
            assert_eq!(ef_view.select(i), Some(v[i]), "view disagrees at {i}");
            assert_eq!(ef_view.select(i), ef.select(i), "view != owned at {i}");
        }
        assert_eq!(ef_view.select(v.len()), None);
    }
}
